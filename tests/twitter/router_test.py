import pytest
from ai_assistant.commands.cookies import _extract_cookies_for_domain
from fastapi.testclient import TestClient

from rssapi.main import app


def _get_twitter_cookie_string() -> str:
    for domain in ("x.com", "twitter.com"):
        cookies = _extract_cookies_for_domain(domain)
        if "auth_token" in cookies and "ct0" in cookies:
            return "; ".join(f"{k}={v}" for k, v in cookies.items())
    pytest.skip("No valid Twitter/X cookies found in local browser")


@pytest.fixture(scope="module")
def client():
    with TestClient(app) as c:
        yield c


@pytest.fixture(scope="module")
def twitter_cookies() -> str:
    return _get_twitter_cookie_string()


def test_timeline_for_you(client: TestClient, twitter_cookies: str):
    response = client.get(
        "/api/rss/twitter/user/timeline/for-you",
        headers={"X-Twitter-Cookie": twitter_cookies},
    )
    assert response.status_code == 200
    data = response.json()
    assert data["items"]


def test_timeline_following(client: TestClient, twitter_cookies: str):
    response = client.get(
        "/api/rss/twitter/user/timeline/following",
        headers={"X-Twitter-Cookie": twitter_cookies},
    )
    assert response.status_code == 200
    data = response.json()
    assert data["items"]


def test_user_posts(client: TestClient, twitter_cookies: str):
    response = client.get(
        "/api/rss/twitter/elonmusk/posts",
        headers={"X-Twitter-Cookie": twitter_cookies},
    )
    assert response.status_code == 200
    data = response.json()
    assert data["items"]
