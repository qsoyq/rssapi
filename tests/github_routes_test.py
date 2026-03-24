import pytest
from fastapi.testclient import TestClient
from tests import Settings

from rssapi.main import app


@pytest.fixture(scope="module")
def client():
    with TestClient(app) as client:
        yield client


def require_github_token() -> str:
    token = Settings().github.test_github_token
    if token is None:
        pytest.skip("No GitHub test token configured")
    return token


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
    token = require_github_token()
    parmas = {}
    if token is not None:
        parmas["token"] = token
    response = client.get(path, params=parmas)
    assert response.status_code == 200, response.text
    assert response.json()["items"]


def test_github_releases_supports_token_header(client: TestClient):
    path = "/api/rss/github/releases/repos/NSRingo/WeatherKit"
    token = require_github_token()
    response = client.get(path, headers={"X-Github-Api-Token": token})
    assert response.status_code == 200, response.text
    assert response.json()["items"]


def test_github_commits_header_token_has_higher_priority_than_query(client: TestClient):
    path = "/api/rss/github/commits/repos/qsoyq/rssapi"
    token = require_github_token()
    response = client.get(
        path,
        params={"token": "invalid-query-token"},
        headers={"X-Github-Api-Token": token},
    )
    assert response.status_code == 200, response.text
    assert response.json()["items"]


def test_github_notifications_supports_query_token(client: TestClient):
    path = "/api/rss/github/notifications/user"
    token = require_github_token()
    response = client.get(path, params={"token": token})
    assert response.status_code == 200, response.text
    assert isinstance(response.json()["items"], list)


def test_github_notifications_header_token_has_higher_priority_than_query(client: TestClient):
    path = "/api/rss/github/notifications/user"
    token = require_github_token()
    response = client.get(
        path,
        params={"token": "invalid-query-token"},
        headers={"X-Github-Api-Token": token},
    )
    assert response.status_code == 200, response.text
    assert isinstance(response.json()["items"], list)
