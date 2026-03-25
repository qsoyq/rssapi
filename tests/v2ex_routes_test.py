import pytest
from fastapi.testclient import TestClient
from tests import Settings

from rssapi.main import app


@pytest.fixture(scope="module")
def client():
    with TestClient(app) as client:
        yield client


def require_v2ex_token() -> str:
    token = Settings().v2ex.test_v2ex_token
    if token is None:
        pytest.skip("No V2EX test token configured")
    return token


def test_v2ex_aggregation(client: TestClient):
    response = client.get("/api/rss/jsonfeed/v2ex/aggregation", params={"topics": ["dns"]})
    assert response.status_code == 200
    assert response.json()["items"]
    assert response.json()["home_page_url"] == "https://v2ex.com/go/dns"


def test_v2ex_notifications_requires_token(client: TestClient):
    path = "/api/rss/jsonfeed/v2ex/notifications"
    response = client.get(path)
    assert response.status_code == 422
    assert response.json()["detail"] == (
        "V2ex API Token is required via query parameter `token` or header `X-V2ex-Api-Token`"
    )


def test_v2ex_notifications_supports_query_token(client: TestClient):
    path = "/api/rss/jsonfeed/v2ex/notifications"
    token = require_v2ex_token()
    response = client.get(path, params={"token": token})
    assert response.status_code == 200, response.text
    assert isinstance(response.json()["items"], list)


def test_v2ex_notifications_path_token_still_works(client: TestClient):
    token = require_v2ex_token()
    response = client.get(f"/api/rss/jsonfeed/v2ex/notifications/{token}")
    assert response.status_code == 200, response.text
    assert isinstance(response.json()["items"], list)


def test_v2ex_notifications_header_token_has_higher_priority_than_query(client: TestClient):
    path = "/api/rss/jsonfeed/v2ex/notifications"
    token = require_v2ex_token()
    response = client.get(
        path,
        params={"token": "invalid-query-token"},
        headers={"X-V2ex-Api-Token": token},
    )
    assert response.status_code == 200, response.text
    assert isinstance(response.json()["items"], list)
