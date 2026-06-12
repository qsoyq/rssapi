import pytest
from fastapi.testclient import TestClient

from rssapi.main import app


@pytest.fixture(scope="module")
def client():
    with TestClient(app) as c:
        yield c


@pytest.mark.skip(reason="requires live Reddit upstream access")
def test_reddit_subreddit_posts(client: TestClient):
    response = client.get("/api/rss/reddit/subreddit/python", params={"max_posts": 3})
    assert response.status_code == 200

    data = response.json()
    assert data["title"] == "r/Python"
    assert data["items"]

    item = data["items"][0]
    assert item["id"]
    assert item["url"].startswith("https://www.reddit.com/")
    assert item["content_html"]
