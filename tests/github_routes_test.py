import pytest
from fastapi.testclient import TestClient
from tests import Settings

from rssapi.main import app


@pytest.fixture(scope="module")
def client():
    with TestClient(app) as client:
        yield client


def test_github_releases(client: TestClient):
    path = "/api/rss/github/releases/repos/NSRingo/WeatherKit"
    token = Settings().github.test_github_token
    parmas = {}
    if token is not None:
        parmas["token"] = token
    response = client.get(path, params=parmas)
    assert response.status_code == 200, response.text
    assert response.json()["items"]


def test_github_commits(client: TestClient):
    path = "/api/rss/github/commits/repos/qsoyq/rssapi"
    token = Settings().github.test_github_token
    parmas = {}
    if token is not None:
        parmas["token"] = token
    response = client.get(path, params=parmas)
    assert response.status_code == 200, response.text
    assert response.json()["items"]


def test_github_issues(client: TestClient):
    path = "/api/rss/github/issues/repos/NSRingo/WeatherKit"
    token = Settings().github.test_github_token
    assert token, token
    parmas = {}
    if token is not None:
        parmas["token"] = token
    response = client.get(path, params=parmas)
    assert response.status_code == 200, response.text
    assert response.json()["items"]
