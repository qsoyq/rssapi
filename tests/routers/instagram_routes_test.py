import json
import threading
import time
from collections.abc import Iterator
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from typing import Any
from urllib.parse import parse_qs, urlparse

import pytest
from fastapi import HTTPException
from fastapi.testclient import TestClient

from rssapi.applications.instagram import utils as instagram_utils
from rssapi.applications.instagram.utils import fetch_user_feed_data, post_to_jsonfeed_item
from rssapi.main import app


def _user(username: str = "he.le_nn", *, is_private: bool = False) -> dict[str, Any]:
    return {
        "id": "1589007020",
        "username": username,
        "full_name": "Helen",
        "is_private": is_private,
        "profile_pic_url": "https://cdn.example/avatar.jpg",
    }


def _image_post(index: int, username: str = "he.le_nn") -> dict[str, Any]:
    return {
        "id": f"post-{index}",
        "pk": str(index),
        "code": f"Code{index}",
        "taken_at": 1_700_000_000 + index,
        "media_type": 1,
        "caption": {"text": f"Caption {index}"},
        "like_count": index,
        "comment_count": index + 1,
        "image_versions2": {"candidates": [{"url": f"https://cdn.example/image-{index}.jpg?x=1&y=2"}]},
        "user": _user(username),
    }


def _payload(
    username: str,
    items: list[dict[str, Any]],
    *,
    more_available: bool = False,
    next_max_id: str | None = None,
    is_private: bool = False,
) -> dict[str, Any]:
    return {
        "status": "ok",
        "user": _user(username, is_private=is_private),
        "items": items,
        "more_available": more_available,
        "next_max_id": next_max_id,
    }


class LocalInstagramUpstream:
    def __init__(self) -> None:
        self.responses: dict[tuple[str, str | None], tuple[int, Any, float]] = {}
        self.requests: list[dict[str, Any]] = []
        controller = self

        class Handler(BaseHTTPRequestHandler):
            def do_GET(self) -> None:
                parsed = urlparse(self.path)
                parts = parsed.path.strip("/").split("/")
                username = parts[4] if len(parts) >= 6 else ""
                query = parse_qs(parsed.query)
                cursor = query.get("max_id", [None])[0]
                controller.requests.append(
                    {
                        "username": username,
                        "cursor": cursor,
                        "count": query.get("count", [None])[0],
                        "app_id": self.headers.get("X-IG-App-ID"),
                        "cookie": self.headers.get("Cookie"),
                    }
                )
                status_code, body, delay = controller.responses.get(
                    (username, cursor),
                    (404, "not found", 0.0),
                )
                if delay:
                    time.sleep(delay)
                payload = json.dumps(body).encode() if isinstance(body, dict) else str(body).encode()
                self.send_response(status_code)
                self.send_header("Content-Type", "application/json")
                self.send_header("Content-Length", str(len(payload)))
                self.end_headers()
                try:
                    self.wfile.write(payload)
                except BrokenPipeError:
                    pass

            def log_message(self, format: str, *args: object) -> None:
                return

        self.server = ThreadingHTTPServer(("127.0.0.1", 0), Handler)
        self.thread = threading.Thread(target=self.server.serve_forever, daemon=True)

    @property
    def base_url(self) -> str:
        address = self.server.server_address
        host_value = address[0]
        host = host_value.decode() if isinstance(host_value, bytes) else str(host_value)
        port = int(address[1])
        return f"http://{host}:{port}"

    def add(
        self,
        username: str,
        cursor: str | None,
        body: Any,
        *,
        status_code: int = 200,
        delay: float = 0.0,
    ) -> None:
        self.responses[(username, cursor)] = (status_code, body, delay)

    def start(self) -> None:
        self.thread.start()

    def close(self) -> None:
        self.server.shutdown()
        self.server.server_close()
        self.thread.join()


@pytest.fixture
def instagram_upstream() -> Iterator[LocalInstagramUpstream]:
    upstream = LocalInstagramUpstream()
    upstream.start()
    try:
        yield upstream
    finally:
        upstream.close()


def test_post_to_jsonfeed_item_renders_image_caption_metrics_and_location() -> None:
    post = _image_post(1)
    post["caption"] = {"text": "<First line>\n#travel"}
    post["location"] = {"name": "A&B"}

    item = post_to_jsonfeed_item(post, _user(), "he.le_nn")

    assert item.id == "post-1"
    assert item.title == "<First line>"
    assert str(item.url) == "https://www.instagram.com/p/Code1/"
    assert item.date_published == "2023-11-14T22:13:21+00:00"
    assert item.author and item.author.name == "Helen"
    assert item.image and str(item.image).startswith("https://cdn.example/image-1.jpg")
    content_html = item.content_html or ""
    assert content_html.index("<div>") < content_html.index("<details>")
    assert content_html.startswith('<div><img src="https://cdn.example/image-1.jpg?x=1&amp;y=2"')
    assert content_html.endswith(
        "<details><summary>查看正文</summary>"
        "<p>&lt;First line&gt;<br>#travel</p>"
        "<p>❤️ 1 · 💬 2 · 📍 A&amp;B</p>"
        "</details>"
    )
    assert " open" not in content_html


def test_post_to_jsonfeed_item_renders_video_and_mixed_carousel() -> None:
    video = {
        "id": "video-1",
        "media_type": 2,
        "image_versions2": {"candidates": [{"url": "https://cdn.example/poster.jpg"}]},
        "video_versions": [{"url": "https://cdn.example/video.mp4?x=1&y=2"}],
    }
    post = _image_post(2)
    post["media_type"] = 8
    post["carousel_media"] = [_image_post(21), video]

    item = post_to_jsonfeed_item(post, _user(), "he.le_nn")

    content_html = item.content_html or ""
    assert content_html.count("<img ") == 1
    assert content_html.count("<video ") == 1
    assert content_html.index("<div>") < content_html.index("<details>")
    assert content_html.index("<img ") < content_html.index("<video ")
    assert 'poster="https://cdn.example/poster.jpg"' in content_html
    assert "<details><summary>查看正文</summary>" in content_html
    assert item.attachments and len(item.attachments) == 1
    assert item.attachments[0].mime_type == "video/mp4"
    assert str(item.attachments[0].url).startswith("https://cdn.example/video.mp4")


def test_post_to_jsonfeed_item_renders_collapsible_body_without_media() -> None:
    post = {
        "id": "text-only-1",
        "code": "TextOnly1",
        "caption": {"text": "A text-only post"},
        "like_count": 3,
        "comment_count": 4,
        "location": {"name": "Somewhere"},
        "user": _user(),
    }

    item = post_to_jsonfeed_item(post, _user(), "he.le_nn")

    assert item.content_html == (
        "<details><summary>查看正文</summary><p>A text-only post</p><p>❤️ 3 · 💬 4 · 📍 Somewhere</p></details>"
    )


def test_post_to_jsonfeed_item_does_not_render_empty_details_for_media_only() -> None:
    post = _image_post(4)
    post.pop("caption")
    post.pop("like_count")
    post.pop("comment_count")

    item = post_to_jsonfeed_item(post, _user(), "he.le_nn")

    assert item.content_html and item.content_html.startswith("<div><img ")
    assert "<details>" not in item.content_html


def test_post_to_jsonfeed_item_handles_missing_caption_and_unknown_media() -> None:
    post = {"id": "unknown-1", "code": "Unknown1", "media_type": 99, "user": _user()}

    item = post_to_jsonfeed_item(post, _user(), "he.le_nn")

    assert item.title == "Instagram post Unknown1"
    assert item.content_html == "<p>Instagram post</p>"
    assert item.attachments is None


def test_post_to_jsonfeed_item_skips_invalid_upstream_urls() -> None:
    post = _image_post(3)
    post["image_versions2"] = {"candidates": [{"url": "javascript:alert(1)"}]}
    post["media_type"] = 2
    post["video_versions"] = [{"url": "not-a-url"}]
    post["user"]["profile_pic_url"] = "data:text/html,unsafe"

    item = post_to_jsonfeed_item(post, _user(), "he.le_nn")

    assert item.image is None
    assert item.attachments is None
    assert "javascript:" not in (item.content_html or "")
    assert "not-a-url" not in (item.content_html or "")
    assert item.author and item.author.avatar is None


@pytest.mark.asyncio
async def test_fetch_user_feed_paginates_deduplicates_and_preserves_order(
    instagram_upstream: LocalInstagramUpstream,
) -> None:
    username = "pagination_user"
    first_page = [_image_post(index, username) for index in range(12)]
    second_page = [_image_post(index, username) for index in range(11, 24)]
    instagram_upstream.add(
        username,
        None,
        _payload(username, first_page, more_available=True, next_max_id="cursor-1"),
    )
    instagram_upstream.add(username, "cursor-1", _payload(username, second_page))

    user, items = await fetch_user_feed_data(username, 20, base_url=instagram_upstream.base_url)

    assert user["username"] == username
    assert [item["id"] for item in items] == [f"post-{index}" for index in range(20)]
    assert [request["cursor"] for request in instagram_upstream.requests] == [None, "cursor-1"]
    assert all(request["count"] == "12" for request in instagram_upstream.requests)
    assert all(request["app_id"] == "936619743392459" for request in instagram_upstream.requests)


@pytest.mark.asyncio
async def test_fetch_user_feed_supports_maximum_50_posts(instagram_upstream: LocalInstagramUpstream) -> None:
    username = "fifty_user"
    for page in range(5):
        cursor = None if page == 0 else f"cursor-{page}"
        next_cursor = f"cursor-{page + 1}"
        start = page * 12
        instagram_upstream.add(
            username,
            cursor,
            _payload(
                username,
                [_image_post(index, username) for index in range(start, start + 12)],
                more_available=True,
                next_max_id=next_cursor,
            ),
        )

    _, items = await fetch_user_feed_data(username, 50, base_url=instagram_upstream.base_url)

    assert len(items) == 50
    assert items[0]["id"] == "post-0"
    assert items[-1]["id"] == "post-49"
    assert len(instagram_upstream.requests) == 5


@pytest.mark.asyncio
async def test_fetch_user_feed_stops_on_repeated_cursor(instagram_upstream: LocalInstagramUpstream) -> None:
    username = "repeat_cursor_user"
    instagram_upstream.add(
        username,
        None,
        _payload(username, [_image_post(1, username)], more_available=True, next_max_id="same"),
    )
    instagram_upstream.add(
        username,
        "same",
        _payload(username, [_image_post(2, username)], more_available=True, next_max_id="same"),
    )

    _, items = await fetch_user_feed_data(username, 12, base_url=instagram_upstream.base_url)

    assert [item["id"] for item in items] == ["post-1", "post-2"]
    assert len(instagram_upstream.requests) == 2


@pytest.mark.asyncio
async def test_fetch_user_feed_caps_pages_when_upstream_returns_no_new_items(
    instagram_upstream: LocalInstagramUpstream,
) -> None:
    username = "empty_pages_user"
    instagram_upstream.add(
        username,
        None,
        _payload(username, [], more_available=True, next_max_id="cursor-1"),
    )
    instagram_upstream.add(
        username,
        "cursor-1",
        _payload(username, [], more_available=True, next_max_id="cursor-2"),
    )

    _, items = await fetch_user_feed_data(username, 12, base_url=instagram_upstream.base_url)

    assert items == []
    assert len(instagram_upstream.requests) == 2


@pytest.mark.asyncio
@pytest.mark.parametrize(
    ("username", "status_code", "body", "expected_status"),
    [
        ("missing_user", 404, "not found", 404),
        ("limited_user", 429, {"status": "fail"}, 429),
        ("html_user", 200, "<html>login</html>", 502),
        ("invalid_user", 200, {"status": "fail", "items": []}, 502),
        ("missing_items_user", 200, {"status": "ok"}, 502),
        ("soft_login_user", 200, {"status": "ok", "items": []}, 401),
        ("login_redirect_user", 302, "", 401),
    ],
)
async def test_fetch_user_feed_maps_upstream_errors(
    instagram_upstream: LocalInstagramUpstream,
    username: str,
    status_code: int,
    body: Any,
    expected_status: int,
) -> None:
    instagram_upstream.add(username, None, body, status_code=status_code)

    with pytest.raises(HTTPException) as exc_info:
        await fetch_user_feed_data(username, 12, base_url=instagram_upstream.base_url)

    assert exc_info.value.status_code == expected_status
    if expected_status == 401:
        assert exc_info.value.detail == (
            "Instagram authentication required; provide cookies or X-Instagram-Cookie "
            "containing ds_user_id and sessionid"
        )


@pytest.mark.asyncio
async def test_fetch_user_feed_sends_cookies(instagram_upstream: LocalInstagramUpstream) -> None:
    username = "cookie_user"
    cookies = "ds_user_id=123; sessionid=abc"
    instagram_upstream.add(username, None, _payload(username, [_image_post(1, username)]))

    _, items = await fetch_user_feed_data(username, 12, base_url=instagram_upstream.base_url, cookies=cookies)

    assert len(items) == 1
    assert instagram_upstream.requests[0]["cookie"] == cookies


@pytest.mark.asyncio
async def test_fetch_user_feed_rejects_private_profile(instagram_upstream: LocalInstagramUpstream) -> None:
    username = "private_user"
    instagram_upstream.add(username, None, _payload(username, [], is_private=True))

    with pytest.raises(HTTPException) as exc_info:
        await fetch_user_feed_data(username, 12, base_url=instagram_upstream.base_url)

    assert exc_info.value.status_code == 403


@pytest.mark.asyncio
async def test_fetch_user_feed_maps_timeout(instagram_upstream: LocalInstagramUpstream) -> None:
    username = "slow_user"
    instagram_upstream.add(username, None, _payload(username, []), delay=0.1)

    with pytest.raises(HTTPException) as exc_info:
        await fetch_user_feed_data(username, 12, base_url=instagram_upstream.base_url, timeout=0.01)

    assert exc_info.value.status_code == 504


def test_instagram_route_returns_json_feed_and_uses_cache(
    instagram_upstream: LocalInstagramUpstream,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    username = "route_user"
    instagram_upstream.add(username, None, _payload(username, [_image_post(1, username)]))
    monkeypatch.setattr(instagram_utils, "INSTAGRAM_API_BASE_URL", instagram_upstream.base_url)

    with TestClient(app) as client:
        first_response = client.get(f"/api/rss/instagram/{username}/posts")
        second_response = client.get(f"/api/rss/instagram/{username}/posts")

    assert first_response.status_code == 200, first_response.text
    assert first_response.headers["content-type"].startswith("application/feed+json")
    data = first_response.json()
    assert data["title"] == f"Helen (@{username}) 的 Instagram 贴文"
    assert data["author"]["url"] == f"https://www.instagram.com/{username}/"
    assert data["home_page_url"] == ""
    assert data["items"][0]["url"] == "https://www.instagram.com/p/Code1/"
    content_html = data["items"][0]["content_html"]
    assert content_html.index("</details>") < content_html.index("查看原贴")
    assert second_response.status_code == 200
    assert len(instagram_upstream.requests) == 1


def test_instagram_route_rejects_soft_login_response(
    instagram_upstream: LocalInstagramUpstream,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    username = "soft_login_route_user"
    instagram_upstream.add(username, None, {"status": "ok", "items": []})
    monkeypatch.setattr(instagram_utils, "INSTAGRAM_API_BASE_URL", instagram_upstream.base_url)

    with TestClient(app) as client:
        response = client.get(f"/api/rss/instagram/{username}/posts")

    assert response.status_code == 401
    assert response.json()["detail"] == (
        "Instagram authentication required; provide cookies or X-Instagram-Cookie containing ds_user_id and sessionid"
    )


@pytest.mark.parametrize(
    ("params", "headers", "expected_cookie"),
    [
        ({"cookies": "ds_user_id=query; sessionid=query"}, {}, "ds_user_id=query; sessionid=query"),
        ({}, {"X-Instagram-Cookie": "ds_user_id=header; sessionid=header"}, "ds_user_id=header; sessionid=header"),
        (
            {"cookies": "ds_user_id=query; sessionid=query"},
            {"X-Instagram-Cookie": "ds_user_id=header; sessionid=header"},
            "ds_user_id=query; sessionid=query",
        ),
    ],
)
def test_instagram_route_accepts_cookies_from_query_or_header(
    instagram_upstream: LocalInstagramUpstream,
    monkeypatch: pytest.MonkeyPatch,
    params: dict[str, str],
    headers: dict[str, str],
    expected_cookie: str,
) -> None:
    username = f"cookie_route_{len(params)}_{len(headers)}"
    instagram_upstream.add(username, None, _payload(username, [_image_post(1, username)]))
    monkeypatch.setattr(instagram_utils, "INSTAGRAM_API_BASE_URL", instagram_upstream.base_url)

    with TestClient(app) as client:
        response = client.get(f"/api/rss/instagram/{username}/posts", params=params, headers=headers)

    assert response.status_code == 200, response.text
    assert instagram_upstream.requests[0]["cookie"] == expected_cookie
    assert "cookies=" not in response.json()["feed_url"]


@pytest.mark.parametrize("username", ["bad-name", "a" * 31])
def test_instagram_route_validates_username(username: str) -> None:
    with TestClient(app) as client:
        response = client.get(f"/api/rss/instagram/{username}/posts")

    assert response.status_code == 422


@pytest.mark.parametrize("max_posts", [0, 51])
def test_instagram_route_validates_max_posts(max_posts: int) -> None:
    with TestClient(app) as client:
        response = client.get("/api/rss/instagram/valid_user/posts", params={"max_posts": max_posts})

    assert response.status_code == 422
