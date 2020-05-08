#!/usr/bin/python

import time
import requests
import argparse
from pprint import pprint
import datetime
import os
from sys import exit

from prometheus_client import start_http_server, Summary
from prometheus_client.core import GaugeMetricFamily, REGISTRY

DEBUG = int(os.environ.get('DEBUG', '0'))

COLLECTION_TIME = Summary('jenkins_collector_collect_seconds',
                          'Time spent to collect metrics from Jenkins')


class JenkinsCollector(object):
    def __init__(self, target, user, password, insecure):
        self._target = target.rstrip("/")
        self._user = user
        self._password = password
        self._insecure = insecure

    def collect(self):
        start = time.time()

        # Request data from Jenkins
        jobs = [{
            'fullName': 'consumer-fresh-env-tests/master',
            'builds': self._request_data()
        }]

        self._setup_empty_prometheus_metrics()

        for job in jobs:
            print(job)
            name = job['fullName']
            if DEBUG:
                print("Found Job: {}".format(name))
                pprint(job)

            self._get_metrics(name, job)

        for metric in self._prometheus_metrics.values():
            yield metric

        duration = time.time() - start
        COLLECTION_TIME.observe(duration)

    def _request_data(self):
        # Request exactly the information we need from Jenkins
        url = '{0}/job/consumer-fresh-env-tests/job/master/api/json'.format(
            self._target)
        tree = 'builds[url,duration,result,timestamp]'

        params = {
            'tree': tree,
        }

        def parsejobs(myurl):
            if self._user and self._password:
                response = requests.get(
                    myurl, params=params, auth=(self._user, self._password),
                    verify=(not self._insecure))
            else:
                response = requests.get(
                    myurl, params=params, verify=(not self._insecure))
            if DEBUG:
                pprint(response.text)
            if response.status_code != requests.codes.ok:
                raise Exception("Call to url %s failed with status: %s" % (
                    myurl, response.status_code))
            result = response.json()
            if DEBUG:
                pprint(result)

            lookup_interval = datetime.timedelta(hours=1)
            filter_lower_bound = datetime.datetime.now() - lookup_interval

            filtered_builds = []

            for build in result['builds']:
                if build['timestamp'] > filter_lower_bound.timestamp() * 1000:
                    filtered_builds.append(build)

            return filtered_builds

        return parsejobs(url)

    def _setup_empty_prometheus_metrics(self):
        # The metrics we want to export.
        self._prometheus_metrics = {}

        self._prometheus_metrics = {
            'totalDurationMillis': GaugeMetricFamily(
                'jenkins_job_monitor_total_duration_seconds_sum',
                'Jenkins build total duration in millis',
                labels=["jobname"]),

            'failCount': GaugeMetricFamily(
                'jenkins_job_monitor_fail_count',
                'Jenkins build fail counts',
                labels=["jobname"]),
            'totalCount': GaugeMetricFamily(
                'jenkins_job_monitor_total_count',
                'Jenkins build total counts',
                labels=["jobname"]),
            'passCount': GaugeMetricFamily(
                'jenkins_job_monitor_pass_count',
                'Jenkins build pass counts',
                labels=["jobname"]),
            'pendingCount': GaugeMetricFamily(
                'jenkins_job_monitor_pending_count',
                'Jenkins build pending counts',
                labels=["jobname"]),
        }

    def _get_metrics(self, name, job):
        build_data = job['builds'] or {}
        self._add_data_to_prometheus_structure(build_data, job, name)

    def _add_data_to_prometheus_structure(self, build_data, job, name):
        finished = list(filter(lambda x: x['duration'] != 0, build_data))
        pending = list(filter(lambda x: x['duration'] == 0, build_data))
        successful = list(filter(
            lambda x: x['result'] == 'SUCCESS', build_data))
        failed = list(filter(
            lambda x: x['result'] in ['FAILURE', 'ABORTED'], build_data))

        self._prometheus_metrics['passCount'].add_metric(
            [name], len(successful))
        self._prometheus_metrics['failCount'].add_metric(
            [name], len(failed))
        self._prometheus_metrics['pendingCount'].add_metric(
            [name], len(pending))
        self._prometheus_metrics['totalCount'].add_metric(
            [name], len(finished))

        total_duration = 0
        for build in build_data:
            duration = build.get("duration")
            if duration == 0:
                duration = time.time() * 1000 - build.get('timestamp')

            total_duration += duration / 1000.0

        self._prometheus_metrics['totalDurationMillis'].add_metric(
            [name], total_duration)


def parse_args():
    parser = argparse.ArgumentParser(
        description='jenkins exporter args jenkins address and port'
    )
    parser.add_argument(
        '-j', '--jenkins',
        metavar='jenkins',
        required=False,
        help='server url from the jenkins api',
        default=os.environ.get('JENKINS_SERVER', 'http://jenkins:8080')
    )
    parser.add_argument(
        '--user',
        metavar='user',
        required=False,
        help='jenkins api user',
        default=os.environ.get('JENKINS_USER')
    )
    parser.add_argument(
        '--password',
        metavar='password',
        required=False,
        help='jenkins api password',
        default=os.environ.get('JENKINS_PASSWORD')
    )
    parser.add_argument(
        '-p', '--port',
        metavar='port',
        required=False,
        type=int,
        help='Listen to this port',
        default=int(os.environ.get('VIRTUAL_PORT', '9118'))
    )
    parser.add_argument(
        '-k', '--insecure',
        dest='insecure',
        required=False,
        action='store_true',
        help='Allow connection to insecure Jenkins API',
        default=False
    )
    return parser.parse_args()


def main():
    try:
        args = parse_args()
        port = int(args.port)
        REGISTRY.register(JenkinsCollector(
            args.jenkins, args.user, args.password, args.insecure
        ))
        start_http_server(port)
        print("Polling {}. Serving at port: {}".format(args.jenkins, port))
        while True:
            time.sleep(1)
    except KeyboardInterrupt:
        print(" Interrupted")
        exit(0)


if __name__ == "__main__":
    main()
