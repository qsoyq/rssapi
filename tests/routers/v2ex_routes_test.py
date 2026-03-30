import pytest
from fastapi.testclient import TestClient
from tests import Settings

from rssapi.applications.v2ex.router import _resolve_favorite_session_key
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


def require_v2ex_session_key() -> str:
    session_key = Settings().v2ex.test_v2ex_session_key
    if session_key is None:
        pytest.skip("No V2EX test session key configured")
    return session_key


def test_v2ex_aggregation(client: TestClient):
    response = client.get("/api/rss/jsonfeed/v2ex/aggregation", params={"topics": ["dns"]})
    assert response.status_code == 200
    assert response.json()["items"]
    assert response.json()["home_page_url"] == "https://v2ex.com/go/dns"


def test_v2ex_favorite_requires_session_key(client: TestClient):
    path = "/api/rss/jsonfeed/v2ex/favorite"
    response = client.get(path)
    assert response.status_code == 422
    assert response.json()["detail"] == (
        "V2ex session key from cookies.A2 is required via query parameter `session_key` or header `X-V2ex-Session-Key`"
    )


def test_v2ex_favorite_session_key_header_has_higher_priority_than_query():
    assert _resolve_favorite_session_key("query-session-key", "header-session-key") == "header-session-key"


def test_v2ex_favorite_supports_query_session_key(client: TestClient):
    path = "/api/rss/jsonfeed/v2ex/favorite"
    session_key = require_v2ex_session_key()
    response = client.get(path, params={"session_key": session_key})
    assert response.status_code == 200, response.text
    assert isinstance(response.json()["items"], list)


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
