import pytest
from fastapi import HTTPException
from fastapi.testclient import TestClient

from rssapi.applications.bilibili import router as bilibili_router
from rssapi.main import app


@pytest.fixture(scope="module")
def client():
    with TestClient(app) as client:
        yield client


async def mock_fetch_user_feed_data(mid: int, page_size: int, cookies: str | None = None):
    assert mid == 4186021
    assert page_size == 2
    return {
        "mid": "4186021",
        "name": "初夏ChuXXia",
        "face": "https://i1.hdslb.com/bfs/face/avatar.jpg",
        "sign": "每周史低+初见评测",
    }, [
        {
            "id": "bilibili-video-BV1xx411c7mD",
            "url": "https://www.bilibili.com/video/BV1xx411c7mD",
            "title": "测试视频",
            "content_html": "<p>测试简介</p>",
            "summary": "测试简介",
            "image": "https://i0.hdslb.com/bfs/archive/cover.jpg",
            "date_published": "2024-03-09T16:00:00+00:00",
            "author": {
                "name": "初夏ChuXXia",
                "url": "https://space.bilibili.com/4186021",
                "avatar": "https://i1.hdslb.com/bfs/face/avatar.jpg",
            },
        }
    ]


async def mock_fetch_user_feed_error(mid: int, page_size: int, cookies: str | None = None):
    raise HTTPException(status_code=502, detail="fetch bilibili user videos error: 风控校验失败 (code: -352)")


def test_bilibili_user_videos(client: TestClient, monkeypatch: pytest.MonkeyPatch):
    monkeypatch.setattr(bilibili_router, "fetch_user_feed_data", mock_fetch_user_feed_data)
    response = client.get("/api/rss/bilibili/user/4186021", params={"page_size": 2, "use_cache": False})

    assert response.status_code == 200, response.text
    data = response.json()
    assert data["title"] == "初夏ChuXXia 的 Bilibili 投稿"
    assert data["description"] == "每周史低+初见评测"
    assert data["home_page_url"] == ""
    assert data["author"]["url"] == "https://space.bilibili.com/4186021"
    assert data["icon"] == "https://i1.hdslb.com/bfs/face/avatar.jpg"
    assert data["items"][0]["url"] == "https://www.bilibili.com/video/BV1xx411c7mD"
    assert data["items"][0]["author"]["name"] == "初夏ChuXXia"


def test_bilibili_user_videos_validates_page_size(client: TestClient):
    response = client.get("/api/rss/bilibili/user/4186021", params={"page_size": 51})

    assert response.status_code == 422


def test_bilibili_user_videos_cookie_from_query(client: TestClient, monkeypatch: pytest.MonkeyPatch):
    received: dict[str, str | None] = {}

    async def mock(mid: int, page_size: int, cookies: str | None = None):
        received["cookies"] = cookies
        return await mock_fetch_user_feed_data(mid, page_size)

    monkeypatch.setattr(bilibili_router, "fetch_user_feed_data", mock)
    response = client.get(
        "/api/rss/bilibili/user/4186021",
        params={"page_size": 2, "use_cache": False, "cookies": "SESSDATA=abc"},
    )

    assert response.status_code == 200, response.text
    assert received["cookies"] == "SESSDATA=abc"


def test_bilibili_user_videos_cookie_from_header(client: TestClient, monkeypatch: pytest.MonkeyPatch):
    received: dict[str, str | None] = {}

    async def mock(mid: int, page_size: int, cookies: str | None = None):
        received["cookies"] = cookies
        return await mock_fetch_user_feed_data(mid, page_size)

    monkeypatch.setattr(bilibili_router, "fetch_user_feed_data", mock)
    response = client.get(
        "/api/rss/bilibili/user/4186021",
        params={"page_size": 2, "use_cache": False},
        headers={"X-Bilibili-Cookie": "SESSDATA=xyz"},
    )

    assert response.status_code == 200, response.text
    assert received["cookies"] == "SESSDATA=xyz"


def test_bilibili_user_videos_converts_upstream_error(client: TestClient, monkeypatch: pytest.MonkeyPatch):
    monkeypatch.setattr(bilibili_router, "fetch_user_feed_data", mock_fetch_user_feed_error)
    response = client.get("/api/rss/bilibili/user/4186021", params={"page_size": 2, "use_cache": False})

    assert response.status_code == 502
    assert "风控校验失败" in response.json()["detail"]
