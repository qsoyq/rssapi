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


async def mock_fetch_user_feed_data_with_playable_video(mid: int, page_size: int, cookies: str | None = None):
    user, _ = await mock_fetch_user_feed_data(mid, page_size, cookies)
    return user, [
        {
            "id": "bilibili-video-BV1xx411c7mD",
            "url": "https://www.bilibili.com/video/BV1xx411c7mD",
            "title": "测试视频",
            "content_html": (
                '<p><video controls preload="metadata" '
                'src="https://upos-sz-mirror.example.com/video.mp4?deadline=1781890000" '
                'poster="https://i0.hdslb.com/bfs/archive/cover.jpg">测试视频</video></p>'
                '<p><a href="https://upos-sz-mirror.example.com/video.mp4?deadline=1781890000">'
                "视频 CDN 直链（无需 cookies，需要 Bilibili Referer）</a></p>"
            ),
            "summary": "测试简介",
            "image": "https://i0.hdslb.com/bfs/archive/cover.jpg",
            "date_published": "2024-03-09T16:00:00+00:00",
            "attachments": [
                {
                    "url": "https://upos-sz-mirror.example.com/video.mp4?deadline=1781890000",
                    "mime_type": "video/mp4",
                    "title": "视频 CDN 直链（无需 cookies，需要 Bilibili Referer）",
                }
            ],
            "author": {
                "name": "初夏ChuXXia",
                "url": "https://space.bilibili.com/4186021",
                "avatar": "https://i1.hdslb.com/bfs/face/avatar.jpg",
            },
        }
    ]


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


def test_bilibili_user_videos_uses_stable_media_url_for_video_src(client: TestClient, monkeypatch: pytest.MonkeyPatch):
    monkeypatch.setattr(bilibili_router, "fetch_user_feed_data", mock_fetch_user_feed_data_with_playable_video)
    response = client.get("/api/rss/bilibili/user/4186021", params={"page_size": 2, "use_cache": False})

    assert response.status_code == 200, response.text
    item = response.json()["items"][0]
    assert (
        '<video controls preload="metadata" src="http://testserver/api/rss/bilibili/media/BV1xx411c7mD"'
        in item["content_html"]
    )
    assert "https://upos-sz-mirror.example.com/video.mp4?deadline=1781890000" in item["content_html"]
    assert item["attachments"][0]["url"] == "https://upos-sz-mirror.example.com/video.mp4?deadline=1781890000"


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


def test_bilibili_user_submissions(client: TestClient, monkeypatch: pytest.MonkeyPatch):
    monkeypatch.setattr(bilibili_router, "fetch_user_submissions_feed_data", mock_fetch_user_feed_data)
    response = client.get("/api/rss/bilibili/v2/user/4186021", params={"page_size": 2, "use_cache": False})

    assert response.status_code == 200, response.text
    data = response.json()
    assert data["title"] == "初夏ChuXXia 的 Bilibili 投稿"
    assert data["author"]["url"] == "https://space.bilibili.com/4186021"
    assert data["items"][0]["url"] == "https://www.bilibili.com/video/BV1xx411c7mD"


def test_bilibili_user_submissions_uses_stable_media_url_for_video_src(
    client: TestClient, monkeypatch: pytest.MonkeyPatch
):
    monkeypatch.setattr(
        bilibili_router,
        "fetch_user_submissions_feed_data",
        mock_fetch_user_feed_data_with_playable_video,
    )
    response = client.get("/api/rss/bilibili/v2/user/4186021", params={"page_size": 2, "use_cache": False})

    assert response.status_code == 200, response.text
    item = response.json()["items"][0]
    assert (
        '<video controls preload="metadata" src="http://testserver/api/rss/bilibili/media/BV1xx411c7mD"'
        in item["content_html"]
    )
    assert "https://upos-sz-mirror.example.com/video.mp4?deadline=1781890000" in item["content_html"]
    assert item["attachments"][0]["url"] == "https://upos-sz-mirror.example.com/video.mp4?deadline=1781890000"


def test_bilibili_user_submissions_validates_page_size(client: TestClient):
    response = client.get("/api/rss/bilibili/v2/user/4186021", params={"page_size": 51})

    assert response.status_code == 422


def test_bilibili_user_submissions_cookie_from_query(client: TestClient, monkeypatch: pytest.MonkeyPatch):
    received: dict[str, str | None] = {}

    async def mock(mid: int, page_size: int, cookies: str | None = None):
        received["cookies"] = cookies
        return await mock_fetch_user_feed_data(mid, page_size)

    monkeypatch.setattr(bilibili_router, "fetch_user_submissions_feed_data", mock)
    response = client.get(
        "/api/rss/bilibili/v2/user/4186021",
        params={"page_size": 2, "use_cache": False, "cookies": "SESSDATA=abc"},
    )

    assert response.status_code == 200, response.text
    assert received["cookies"] == "SESSDATA=abc"


def test_bilibili_user_submissions_cookie_from_header(client: TestClient, monkeypatch: pytest.MonkeyPatch):
    received: dict[str, str | None] = {}

    async def mock(mid: int, page_size: int, cookies: str | None = None):
        received["cookies"] = cookies
        return await mock_fetch_user_feed_data(mid, page_size)

    monkeypatch.setattr(bilibili_router, "fetch_user_submissions_feed_data", mock)
    response = client.get(
        "/api/rss/bilibili/v2/user/4186021",
        params={"page_size": 2, "use_cache": False},
        headers={"X-Bilibili-Cookie": "SESSDATA=xyz"},
    )

    assert response.status_code == 200, response.text
    assert received["cookies"] == "SESSDATA=xyz"


def test_bilibili_user_submissions_converts_upstream_error(client: TestClient, monkeypatch: pytest.MonkeyPatch):
    monkeypatch.setattr(bilibili_router, "fetch_user_submissions_feed_data", mock_fetch_user_feed_error)
    response = client.get("/api/rss/bilibili/v2/user/4186021", params={"page_size": 2, "use_cache": False})

    assert response.status_code == 502
    assert "风控校验失败" in response.json()["detail"]


def test_bilibili_media_proxies_range_with_video_referer(client: TestClient, monkeypatch: pytest.MonkeyPatch):
    received: dict[str, str | dict[str, str] | bool] = {}

    async def fetch_playable_video_url(client, video):
        received["video"] = video["bvid"]
        return "https://upos-sz-mirror.example.com/video.mp4?deadline=1781890000"

    class UpstreamResponse:
        status_code = 206
        headers = {
            "content-type": "video/mp4",
            "content-length": "4",
            "content-range": "bytes 0-3/10",
            "accept-ranges": "bytes",
        }

        async def aiter_bytes(self, chunk_size: int):
            received["chunk_size"] = str(chunk_size)
            yield b"test"

        async def aread(self):
            return b""

        async def aclose(self):
            received["response_closed"] = True

    class AsyncClient:
        def __init__(self, timeout, follow_redirects: bool):
            received["timeout"] = str(timeout)
            received["follow_redirects"] = follow_redirects

        def build_request(self, method: str, playable_url: str, headers: dict[str, str]):
            received["method"] = method
            received["playable_url"] = playable_url
            received["headers"] = headers
            return {"method": method, "url": playable_url, "headers": headers}

        async def send(self, request, stream: bool):
            received["stream"] = stream
            return UpstreamResponse()

        async def aclose(self):
            received["client_closed"] = True

    monkeypatch.setattr(bilibili_router, "fetch_playable_video_url", fetch_playable_video_url)
    monkeypatch.setattr(bilibili_router.httpx, "AsyncClient", AsyncClient)

    response = client.get("/api/rss/bilibili/media/BV1xx411c7mD", headers={"Range": "bytes=0-3"})

    assert response.status_code == 206, response.text
    assert response.content == b"test"
    assert response.headers["content-range"] == "bytes 0-3/10"
    assert response.headers["cache-control"] == "no-store"
    assert received["video"] == "BV1xx411c7mD"
    assert received["playable_url"] == "https://upos-sz-mirror.example.com/video.mp4?deadline=1781890000"
    headers = received["headers"]
    assert isinstance(headers, dict)
    assert headers["Referer"] == "https://www.bilibili.com/video/BV1xx411c7mD"
    assert headers["Range"] == "bytes=0-3"
    assert received["method"] == "GET"
    assert received["stream"] is True
    assert received["follow_redirects"] is True
    assert received["response_closed"] is True
    assert received["client_closed"] is True
