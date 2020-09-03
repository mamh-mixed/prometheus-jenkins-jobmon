from unittest.mock import patch, call, Mock

import pytest

from jenkins_exporter.client import JenkinsClient

jenkins_host = "http://jenkins.example.com"
client = JenkinsClient(jenkins_host, "foobar", "secret")


@patch.object(client, "_make_request")
def test_get_jobs(mock_make_request):
    expected = ["master", "alpha", "beta"]
    mock_response = {
        "_class": "org.jenkinsci.plugins.workflow.multibranch.WorkflowMultiBranchProject",
        "jobs": [
            {
                "_class": "org.jenkinsci.plugins.workflow.job.WorkflowJob",
                "name": "master",
            },
            {
                "_class": "org.jenkinsci.plugins.workflow.job.WorkflowJob",
                "name": "alpha",
            },
            {
                "_class": "org.jenkinsci.plugins.workflow.job.WorkflowJob",
                "name": "beta",
            },
        ],
    }

    mock_make_request.return_value = mock_response

    assert expected == client.get_jobs("example")
    mock_make_request.assert_called_with(
        "job/example/api/json?tree=jobs[name]", {"tree": "jobs[name]"}
    )


@patch.object(client, "_make_request")
def test_get_builds(mock_make_request):
    def get_mock_request_data(url, params=None, **kwargs):
        if url == "job/example/job/master/api/json":
            return {
                "builds": [
                    {
                        "duration": 579365,
                        "number": 4,
                        "result": "FAILURE",
                        "timestamp": 1596101460982,
                    },
                    {
                        "duration": 907114,
                        "number": 5,
                        "result": "FAILURE",
                        "timestamp": 1596099716442,
                    },
                ]
            }
        elif url == "job/example/job/master/4/wfapi/describe":
            return {
                "stages": [
                    {
                        "id": "21",
                        "name": "Build",
                        "execNode": "",
                        "status": "SUCCESS",
                        "startTimeMillis": 1598819899396,
                        "durationMillis": 31996,
                        "pauseDurationMillis": 0,
                    },
                    {
                        "id": "30",
                        "name": "Deploy",
                        "execNode": "",
                        "status": "IN_PROGRESS",
                        "startTimeMillis": 1598819931405,
                        "durationMillis": 272045,
                        "pauseDurationMillis": 0,
                    },
                ]
            }

        elif url == "job/example/job/master/5/wfapi/describe":
            return {
                "stages": [
                    {
                        "id": "22",
                        "name": "Build",
                        "execNode": "",
                        "status": "SUCCESS",
                        "startTimeMillis": 1598819899396,
                        "durationMillis": 31996,
                        "pauseDurationMillis": 0,
                    },
                    {
                        "id": "33",
                        "name": "Publish",
                        "execNode": "",
                        "status": "IN_PROGRESS",
                        "startTimeMillis": 1598819931405,
                        "durationMillis": 272045,
                        "pauseDurationMillis": 0,
                    },
                ]
            }

    expected = [
        {
            "duration": 579365,
            "number": 4,
            "result": "FAILURE",
            "timestamp": 1596101460982,
            "stages": [
                {
                    "id": "21",
                    "name": "Build",
                    "execNode": "",
                    "status": "SUCCESS",
                    "startTimeMillis": 1598819899396,
                    "durationMillis": 31996,
                    "pauseDurationMillis": 0,
                },
                {
                    "id": "30",
                    "name": "Deploy",
                    "execNode": "",
                    "status": "IN_PROGRESS",
                    "startTimeMillis": 1598819931405,
                    "durationMillis": 272045,
                    "pauseDurationMillis": 0,
                },
            ],
        },
        {
            "duration": 907114,
            "number": 5,
            "result": "FAILURE",
            "timestamp": 1596099716442,
            "stages": [
                {
                    "id": "22",
                    "name": "Build",
                    "execNode": "",
                    "status": "SUCCESS",
                    "startTimeMillis": 1598819899396,
                    "durationMillis": 31996,
                    "pauseDurationMillis": 0,
                },
                {
                    "id": "33",
                    "name": "Publish",
                    "execNode": "",
                    "status": "IN_PROGRESS",
                    "startTimeMillis": 1598819931405,
                    "durationMillis": 272045,
                    "pauseDurationMillis": 0,
                },
            ],
        },
    ]

    mock_make_request.side_effect = get_mock_request_data

    assert client.get_builds("example", "master") == expected

    mock_make_request.assert_has_calls(
        [
            call(
                "job/example/job/master/api/json",
                {"tree": "builds[number,duration,result,timestamp]"},
            ),
            call("job/example/job/master/4/wfapi/describe"),
            call("job/example/job/master/5/wfapi/describe"),
        ]
    )


@patch("jenkins_exporter.client.requests")
def test_make_request_should_return_json_from_url(requests_mock):
    expected = {"name": "John"}

    mock_response = Mock()
    mock_response.status_code = 200
    mock_response.json.return_value = expected
    requests_mock.get.return_value = mock_response
    jenkins_client = JenkinsClient(jenkins_host)
    url = "job/master"
    actual = jenkins_client._make_request(url)

    assert expected == actual
    requests_mock.get.assert_called_with(
        f"{jenkins_host}/{url}", params={}, verify=True
    )


@patch("jenkins_exporter.client.requests")
def test_make_request_should_return_json_from_url_without_verifying_ssl(requests_mock):
    expected = {"name": "John"}

    mock_response = Mock()
    mock_response.status_code = 200
    mock_response.json.return_value = expected
    requests_mock.get.return_value = mock_response
    jenkins_client = JenkinsClient(jenkins_host, insecure=True)
    url = "job/master"
    actual = jenkins_client._make_request(url)

    assert expected == actual
    requests_mock.get.assert_called_with(
        f"{jenkins_host}/{url}", params={}, verify=False
    )


@patch("jenkins_exporter.client.requests")
def test_make_request_should_throw_exception_if_url_return_non200(requests_mock):
    mock_response = Mock()
    mock_response.status_code = 400

    requests_mock.get.return_value = mock_response
    url = "job/master"
    with pytest.raises(Exception) as excinfo:
        client._make_request(url)
    expected = f"Call to url {jenkins_host}/{url} failed with status: 400"
    assert expected == str(excinfo.value)


@patch("jenkins_exporter.client.requests")
def test_make_request_should_call_url_with_authentication(requests_mock):
    expected = {"name": "John"}

    mock_response = Mock()
    mock_response.status_code = 200
    mock_response.json.return_value = expected
    requests_mock.get.return_value = mock_response

    url = "job/master"
    actual = client._make_request(url)

    assert expected == actual
    requests_mock.get.assert_called_with(
        f"{jenkins_host}/{url}", params={}, auth=("foobar", "secret"), verify=True
    )
