#!/usr/bin/python

import argparse
import datetime
import os
import time
from collections import Counter
from pprint import pprint
from sys import exit

import requests
from prometheus_client import start_http_server, Summary
from prometheus_client.core import GaugeMetricFamily, CounterMetricFamily, REGISTRY

DEBUG = int(os.environ.get("DEBUG", "0"))

COLLECTION_TIME = Summary(
    "jenkins_collector_collect_seconds", "Time spent to collect metrics from Jenkins"
)


class JenkinsClient:
    def _init_(self, jenkins_base_url, username, password, insecure=False):
        self._insecure = insecure
        self._password = password
        self._username = username
        self._jenkins_base_url = jenkins_base_url

    def get_builds(self, job_name, branch, filter_func=None):
        url = f"job/{job_name}/job/{branch}/api/json"
        params = {"tree": "builds[number,duration,result,timestamp]"}

        job_info = self._make_request(url, params)

        builds = (
            job_info["builds"]
            if filter is None
            else list(filter(filter_func, job_info["builds"]))
        )

        for build in builds:
            build_info = self.get_build_info(build["number"], job_name, branch)

            # Populate stages data
            build["stages"] = build_info["stages"]

        return builds

    def _make_request(self, url_fragment, params=None):
        if params is None:
            params = {}

        url = f"{self._jenkins_base_url}/{url_fragment}"

        has_auth_credentials = self._username and self._password

        if has_auth_credentials:
            response = requests.get(
                url,
                params=params,
                auth=(self._username, self._password),
                verify=(not self._insecure),
            )
        else:
            response = requests.get(url, params=params, verify=(not self._insecure))

        if response.status_code != requests.codes.ok:
            raise Exception(
                f"Call to url {url} failed with status: {response.status_code}"
            )

        return response.json()

    def get_build_info(self, build_number, job_name, branch):
        url = f"job/{job_name}/job/{branch}/{build_number}/wfapi/describe"
        return self._make_request(url)


def calculate_total_duration(build_data):
    total_duration = 0
    for build in build_data:
        duration = build.get("duration")
        if duration == 0:
            duration = time.time() * 1000 - build.get("timestamp")

        total_duration += duration / 1000.0
    return total_duration


class JenkinsCollector(object):
    def _init_(self, jenkins_client):
        self._jenkins = jenkins_client

    def collect(self):
        start = time.time()

        # Request data from Jenkins
        jobs = [
            {
                "fullName": "consumer-fresh-env-tests/master",
                "builds": self._request_data("consumer-fresh-env-tests", "master"),
            }
        ]

        self._setup_empty_prometheus_metrics()

        for job in jobs:
            print(job)
            name = job["fullName"]
            if DEBUG:
                print("Found Job: {}".format(name))
                pprint(job)

            self._get_metrics(name, job)

        for metric in self._prometheus_metrics.values():
            yield metric

        duration = time.time() - start
        COLLECTION_TIME.observe(duration)

    def _request_data(self, job_name, branch):
        def should_include_build(build):
            lookup_interval = datetime.timedelta(hours=1)
            filter_lower_bound = datetime.datetime.now() - lookup_interval

            return build["timestamp"] > filter_lower_bound.timestamp() * 1000

        return self._jenkins.get_builds(
            job_name, branch, filter_func=should_include_build
        )

    def _setup_empty_prometheus_metrics(self):
        # The metrics we want to export.
        self._prometheus_metrics = {}

        self._prometheus_metrics = {
            "totalDurationMillis": GaugeMetricFamily(
                "jenkins_job_monitor_total_duration_seconds_sum",
                "Jenkins build total duration in millis",
                labels=["jobname"],
            ),
            "failCount": GaugeMetricFamily(
                "jenkins_job_monitor_fail_count",
                "Jenkins build fail counts",
                labels=["jobname"],
            ),
            "totalCount": GaugeMetricFamily(
                "jenkins_job_monitor_total_count",
                "Jenkins build total counts",
                labels=["jobname"],
            ),
            "passCount": GaugeMetricFamily(
                "jenkins_job_monitor_pass_count",
                "Jenkins build pass counts",
                labels=["jobname"],
            ),
            "pendingCount": GaugeMetricFamily(
                "jenkins_job_monitor_pending_count",
                "Jenkins build pending counts",
                labels=["jobname"],
            ),
            "stage_duration": GaugeMetricFamily(
                "jenkins_job_monitor_stage.duration",
                "Jenkins build stage duration in ms",
                labels=["jobname", "stagename", "build"],
            ),
            "stage_pass_count": CounterMetricFamily(
                "jenkins_job_monitor_stage.pass_count",
                "Jenkins build stage pass count",
                labels=["jobname", "stagename"],
            ),
            "stage_fail_count": CounterMetricFamily(
                "jenkins_job_monitor_stage.fail_count",
                "Jenkins build stage fail count",
                labels=["jobname", "stagename"],
            ),
        }

    def _get_metrics(self, name, job):
        build_data = job["builds"] or {}
        self._add_data_to_prometheus_structure(build_data, job, name)

    def _add_data_to_prometheus_structure(self, build_data, job, name):
        finished = list(filter(lambda x: x["duration"] != 0, build_data))
        pending = list(filter(lambda x: x["duration"] == 0, build_data))
        successful = list(filter(lambda x: x["result"] == "SUCCESS", build_data))
        failed = list(
            filter(lambda x: x["result"] in ["FAILURE", "ABORTED"], build_data)
        )

        self._prometheus_metrics["passCount"].add_metric([name], len(successful))
        self._prometheus_metrics["failCount"].add_metric([name], len(failed))
        self._prometheus_metrics["pendingCount"].add_metric([name], len(pending))
        self._prometheus_metrics["totalCount"].add_metric([name], len(finished))

        total_duration = calculate_total_duration(build_data)

        self._prometheus_metrics["totalDurationMillis"].add_metric(
            [name], total_duration
        )

        pass_counter = Counter()
        fail_counter = Counter()

        for build in build_data:
            for stage in build["stages"]:
                labels = [name, stage["name"]]
                self._prometheus_metrics["stage_duration"].add_metric(
                    [*labels, str(build["number"])], stage["durationMillis"]
                )

                if stage["status"] == "SUCCESS":
                    pass_counter.update([stage["name"]])
                else:
                    fail_counter.update([stage["name"]])

        for stage_name, count in pass_counter.items():
            self._prometheus_metrics["stage_pass_count"].add_metric(
                [name, stage_name], count
            )
        for stage_name, count in fail_counter.items():
            self._prometheus_metrics["stage_fail_count"].add_metric(
                [name, stage_name], count
            )


def parse_args():
    parser = argparse.ArgumentParser(
        description="jenkins exporter args jenkins address and port"
    )
    parser.add_argument(
        "-j",
        "--jenkins",
        metavar="jenkins",
        required=False,
        help="server url from the jenkins api",
        default=os.environ.get("JENKINS_SERVER", "http://jenkins:8080"),
    )
    parser.add_argument(
        "--user",
        metavar="user",
        required=False,
        help="jenkins api user",
        default=os.environ.get("JENKINS_USER"),
    )
    parser.add_argument(
        "--password",
        metavar="password",
        required=False,
        help="jenkins api password",
        default=os.environ.get("JENKINS_PASSWORD"),
    )
    parser.add_argument(
        "-p",
        "--port",
        metavar="port",
        required=False,
        type=int,
        help="Listen to this port",
        default=int(os.environ.get("VIRTUAL_PORT", "9118")),
    )
    parser.add_argument(
        "-k",
        "--insecure",
        dest="insecure",
        required=False,
        action="store_true",
        help="Allow connection to insecure Jenkins API",
        default=False,
    )
    return parser.parse_args()


def main():
    try:
        args = parse_args()
        port = int(args.port)
        jenkins_base_url = args.jenkins.rstrip("/")

        jenkins_client = JenkinsClient(
            jenkins_base_url, args.user, args.password, args.insecure
        )
        REGISTRY.register(JenkinsCollector(jenkins_client))

        start_http_server(port)
        print("Polling {}. Serving at port: {}".format(args.jenkins, port))
        while True:
            time.sleep(1)
    except KeyboardInterrupt:
        print(" Interrupted")
        exit(0)
