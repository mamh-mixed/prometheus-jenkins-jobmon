from copy import deepcopy
from unittest import TestCase
from unittest.mock import Mock

import pytest

from jenkins_exporter.collector import JenkinsCollector, Repository


config = {
    "jobs": {
        "job1": {"team": "team1"},
        "job2": {"team": "team1"},
        "job3": {"team": "team2"},
    }
}


repositories = [
    Repository(name=repo, group=repo_config["team"])
    for repo, repo_config in config["jobs"].items()
]


sample_build = {
    "duration": 907114,
    "number": 5,
    "result": "SUCCESS",
    "timestamp": 1596099716442,
    "stages": [
        {
            "id": "22",
            "name": "Build",
            "execNode": "",
            "status": "SUCCESS",
            "durationMillis": 31996,
            "pauseDurationMillis": 0,
        },
        {
            "id": "33",
            "name": "Publish",
            "execNode": "",
            "status": "SUCCESS",
            "durationMillis": 272045,
            "pauseDurationMillis": 0,
        },
    ],
}


class TestJenkinsCollector(TestCase):
    def setUp(self):
        self.jenkins_client = Mock()
        self.collector = JenkinsCollector(self.jenkins_client, repositories)

    def test_get_aggregate_data(self):
        builds = [sample_build] * 2
        failing_build = deepcopy(sample_build)
        failing_build["result"] = "FAILURE"
        builds.append(failing_build)

        metrics = self.collector.get_aggregate_data(builds, "dummy")
        assert metrics["passCount"] == 2
        assert metrics["failCount"] == 1
        assert metrics["totalCount"] == 3
        assert metrics["totalDurationMillis"] == (sample_build["duration"] * 3) / 1000

    def test_get_stages_data(self):
        builds = [sample_build]
        passing_stage = sample_build["stages"][0]

        failing_build = deepcopy(sample_build)
        failing_stage = failing_build["stages"][1]
        failing_stage["status"] = "FAILED"
        builds.append(failing_build)

        metrics = self.collector.get_stages_data(builds, "dummy")
        assert metrics[passing_stage["name"]]["passed"] == 2
        assert metrics[failing_stage["name"]]["failed"] == 1
