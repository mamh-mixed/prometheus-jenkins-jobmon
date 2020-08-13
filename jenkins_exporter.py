#!/usr/bin/python

import argparse
import datetime
import logging
import os
import time
from collections import Counter
from dataclasses import dataclass

import requests
import yaml
from prometheus_client import start_http_server, Summary
from prometheus_client.core import GaugeMetricFamily, CounterMetricFamily, REGISTRY

DEBUG = int(os.environ.get("DEBUG", "0"))

COLLECTION_TIME = Summary(
    "jenkins_collector_collect_seconds", "Time spent to collect metrics from Jenkins"
)

logging.basicConfig(level=logging.WARNING)

logger = logging.getLogger('jenkins_exporter')

logger.setLevel(logging.DEBUG if DEBUG else logging.INFO)


@dataclass
class Repository:
    name: str
    group: str


class JenkinsClient:
    def __init__(self, jenkins_base_url, username, password, insecure=False):
        self._insecure = insecure
        self._password = password
        self._username = username
        self._jenkins_base_url = jenkins_base_url

    def get_jobs(self, parent):
        logger.info("Getting jobs for %s", parent)
        url_job = f"job/{parent}/api/json?tree=jobs[name]"
        params = {"tree": "jobs[name]"}
        response = self._make_request(url_job, params)
        return [job["name"] for job in response["jobs"]]

    def get_builds(self, job_name, branch, filter_func=None):
        logger.info("Getting build for %s and branch %s", job_name, branch)
        start = time.perf_counter()
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

        duration = time.perf_counter() - start
        logger.info("Fetched build info in %s", duration)
        return builds

    def _make_request(self, url_fragment, params=None):
        if params is None:
            params = {}
        start = time.perf_counter()
        url = f"{self._jenkins_base_url}/{url_fragment}"
        logger.debug("Making request to url %s", url)

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

        stop = time.perf_counter()
        logger.debug("Completed request in %s", stop - start)

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
    def __init__(self, jenkins_client, repositories):
        self._jenkins = jenkins_client
        self.repositories = repositories
        self._setup_empty_prometheus_metrics()

    def collect(self):

        # Request data from Jenkins

        for metric in self._prometheus_metrics.values():
            yield metric

    def update_metrics(self):
        logger.info("Collecting metrics")
        start = time.time()
        self._setup_empty_prometheus_metrics()
        for repository in self.repositories:
            try:
                logger.debug("Processing Job %s", repository.name)
                branches = self._jenkins.get_jobs(repository.name)
                for branch in branches:
                    job = f"{repository.name}/{branch}"
                    self._get_metrics(job, repository)
            except BaseException as e:
                logger.exception("Failed collecting metrics %s", e)
        duration = time.time() - start
        logger.info("Completed collecting metrics in %s s", duration)
        COLLECTION_TIME.observe(duration)

    def _request_data(self, name):
        job_name, branch = name.split("/", 2)
        logger.info("Requesting data from %s and branch %s", job_name, branch)

        def should_include_build(build):
            lookup_interval = datetime.timedelta(minutes=1)
            filter_lower_bound = datetime.datetime.now() - lookup_interval

            return (build["timestamp"] + build["duration"]) > filter_lower_bound.timestamp() * 1000

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
                labels=["jobname", "group", "repository"],
            ),
            "failCount": GaugeMetricFamily(
                "jenkins_job_monitor_fail_count",
                "Jenkins build fail counts",
                labels=["jobname", "group", "repository"],
            ),
            "totalCount": GaugeMetricFamily(
                "jenkins_job_monitor_total_count",
                "Jenkins build total counts",
                labels=["jobname", "group", "repository"],
            ),
            "passCount": GaugeMetricFamily(
                "jenkins_job_monitor_pass_count",
                "Jenkins build pass counts",
                labels=["jobname", "group", "repository"],
            ),
            "pendingCount": GaugeMetricFamily(
                "jenkins_job_monitor_pending_count",
                "Jenkins build pending counts",
                labels=["jobname", "group", "repository"],
            ),
            "stage_duration": GaugeMetricFamily(
                "jenkins_job_monitor_stage_duration",
                "Jenkins build stage duration in ms",
                labels=["jobname", "group", "repository", "stagename", "build"],
            ),
            "stage_pass_count": CounterMetricFamily(
                "jenkins_job_monitor_stage_pass_count",
                "Jenkins build stage pass count",
                labels=["jobname", "group", "repository", "stagename"],
            ),
            "stage_fail_count": CounterMetricFamily(
                "jenkins_job_monitor_stage_fail_count",
                "Jenkins build stage fail count",
                labels=["jobname", "group", "repository", "stagename"],
            ),
        }

    def _get_metrics(self, name, repository):
        build_data = self._request_data(name) or {}
        self._add_data_to_prometheus_structure(build_data, name, repository)

    def _add_data_to_prometheus_structure(self, build_data, name, repository):
        finished = len(list(filter(lambda x: x["duration"] != 0, build_data)))
        pending = len(list(filter(lambda x: x["duration"] == 0, build_data)))
        successful = len(list(filter(lambda x: x["result"] == "SUCCESS", build_data)))
        failed = len(list(
            filter(lambda x: x["result"] in ["FAILURE", "ABORTED"], build_data)
        ))

        logger.info("For job %s recorded %s finished %s pending %s successful %s failed", name, finished, pending,
                    successful,
                    failed)

        self._prometheus_metrics["passCount"].add_metric([name, repository.group, repository.name], successful)
        self._prometheus_metrics["failCount"].add_metric([name, repository.group, repository.name], failed)
        self._prometheus_metrics["pendingCount"].add_metric([name, repository.group, repository.name], pending)
        self._prometheus_metrics["totalCount"].add_metric([name, repository.group, repository.name], finished)

        total_duration = calculate_total_duration(build_data)

        self._prometheus_metrics["totalDurationMillis"].add_metric(
            [name, repository.group, repository.name], total_duration
        )

        pass_counter = Counter()
        fail_counter = Counter()

        for build in build_data:
            for stage in build["stages"]:
                labels = [name, repository.group, repository.name, stage["name"]]
                self._prometheus_metrics["stage_duration"].add_metric(
                    [*labels, str(build["number"])], stage["durationMillis"]
                )

                if stage["status"] == "PENDING":
                    logger.debug("Skipping PENDING build %s #%s %s", name, build['number'], stage['name'])
                    continue

                if stage["status"] == "SUCCESS":
                    logger.debug("Recording SUCCESS for %s build #%s and stage %s", name, build['number'],
                                 stage['name'])
                    pass_counter.update([stage["name"]])
                else:
                    logger.debug("Recording FAIL for %s build #%s and stage %s", name, build['number'], stage['name'])
                    fail_counter.update([stage["name"]])

        for stage_name, count in pass_counter.items():
            self._prometheus_metrics["stage_pass_count"].add_metric(
                [name, repository.group, repository.name, stage_name], count
            )
        for stage_name, count in fail_counter.items():
            self._prometheus_metrics["stage_fail_count"].add_metric(
                [name, repository.group, repository.name, stage_name], count
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
    args = parse_args()
    port = int(args.port)
    jenkins_base_url = args.jenkins.rstrip("/")
    with open("config.yml") as config_file:
        config = yaml.safe_load(config_file)

    repositories = [Repository(name=repo, group=repo_config["team"]) for repo, repo_config in config["jobs"].items()]

    jenkins_client = JenkinsClient(
        jenkins_base_url, args.user, args.password, args.insecure
    )
    logger.info("Polling %s", args.jenkins)
    collector = JenkinsCollector(jenkins_client, repositories)
    REGISTRY.register(collector)

    start_http_server(port)
    logger.info("Serving at  port: %s", port)
    while True:
        collector.update_metrics()
        time.sleep(60)


if __name__ == "__main__":
    main()
