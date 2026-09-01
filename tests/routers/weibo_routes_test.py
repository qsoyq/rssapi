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
from starlette.requests import Request

from rssapi.applications.weibo.utils import (
    build_user_feed,
    extract_sub_cookie,
    fetch_user_feed_data,
    post_to_jsonfeed_item,
)
from rssapi.main import app


def _user() -> dict[str, Any]:
    return {
        "id": "1842706721",
        "screen_name": "微博测试用户",
        "description": "<b>测试简介</b>",
        "avatar_hd": "https://cdn.example/avatar.jpg",
    }


def _post(index: int, *, is_long_text: bool = False) -> dict[str, Any]:
    return {
        "id": f"post-{index}",
        "idstr": f"post-{index}",
        "mblogid": f"Mblog{index}",
        "created_at": "Mon Sep 01 12:34:56 +0800 2026",
        "text_raw": f"Post {index}",
        "isLongText": is_long_text,
        "isAd": False,
        "reposts_count": index,
        "comments_count": index + 1,
        "attitudes_count": index + 2,
        "source": "<a>Weibo Web</a>",
        "user": _user(),
        "pic_ids": [f"image-{index}"],
        "pic_infos": {f"image-{index}": {"largest": {"url": f"https://cdn.example/image-{index}.jpg?x=1&y=2"}}},
    }


def _profile_payload(user: dict[str, Any] | None = None) -> dict[str, Any]:
    return {"ok": 1, "data": {"user": user or _user()}}


def _posts_payload(posts: list[dict[str, Any]]) -> dict[str, Any]:
    return {"ok": 1, "data": {"list": posts, "since_id": "next-page"}}


class LocalWeiboUpstream:
    def __init__(self) -> None:
        self.profile_response: tuple[int, Any, float] = (200, _profile_payload(), 0.0)
        self.page_responses: dict[int, tuple[int, Any, float]] = {}
        self.long_text_responses: dict[str, tuple[int, Any, float]] = {}
        self.requests: list[dict[str, Any]] = []
        controller = self

        class Handler(BaseHTTPRequestHandler):
            def do_GET(self) -> None:
                parsed = urlparse(self.path)
                query = parse_qs(parsed.query)
                record = {
                    "path": parsed.path,
                    "uid": query.get("uid", [None])[0],
                    "page": query.get("page", [None])[0],
                    "post_id": query.get("id", [None])[0],
                    "feature": query.get("feature", [None])[0],
                    "cookie": self.headers.get("Cookie"),
                    "xsrf": self.headers.get("X-XSRF-TOKEN"),
                }
                controller.requests.append(record)

                if parsed.path == "/ajax/profile/info":
                    status_code, body, delay = controller.profile_response
                elif parsed.path == "/ajax/statuses/mymblog":
                    page = int(query.get("page", ["1"])[0])
                    status_code, body, delay = controller.page_responses.get(page, (404, "not found", 0.0))
                elif parsed.path == "/ajax/statuses/longtext":
                    post_id = query.get("id", [""])[0]
                    status_code, body, delay = controller.long_text_responses.get(post_id, (404, "not found", 0.0))
                else:
                    status_code, body, delay = 404, "not found", 0.0

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
        port = int(address[1])
        host = host_value.decode() if isinstance(host_value, bytes) else str(host_value)
        return f"http://{host}:{port}"

    def add_page(
        self,
        page: int,
        posts: list[dict[str, Any]] | Any,
        *,
        status_code: int = 200,
        delay: float = 0.0,
    ) -> None:
        body = _posts_payload(posts) if isinstance(posts, list) else posts
        self.page_responses[page] = (status_code, body, delay)

    def add_long_text(
        self,
        post_id: str,
        body: Any,
        *,
        status_code: int = 200,
    ) -> None:
        self.long_text_responses[post_id] = (status_code, body, 0.0)

    def start(self) -> None:
        self.thread.start()

    def close(self) -> None:
        self.server.shutdown()
        self.server.server_close()
        self.thread.join()


@pytest.fixture
def weibo_upstream() -> Iterator[LocalWeiboUpstream]:
    upstream = LocalWeiboUpstream()
    upstream.start()
    try:
        yield upstream
    finally:
        upstream.close()


def _request(query_string: bytes = b"") -> Request:
    return Request(
        {
            "type": "http",
            "scheme": "https",
            "server": ("rss.example", 443),
            "path": "/api/rss/weibo/1842706721/posts",
            "query_string": query_string,
            "headers": [],
        }
    )


def test_extract_sub_cookie_keeps_only_minimum_credential() -> None:
    assert extract_sub_cookie("SUB=minimum; XSRF-TOKEN=ignored; SUBP=ignored") == "SUB=minimum"
    assert extract_sub_cookie("XSRF-TOKEN=missing-sub") is None
    assert extract_sub_cookie(None) is None


@pytest.mark.asyncio
async def test_fetch_user_feed_paginates_deduplicates_and_only_sends_sub(
    weibo_upstream: LocalWeiboUpstream,
) -> None:
    first_page = [_post(index) for index in range(20)]
    advertisement = _post(999)
    advertisement["isAd"] = True
    first_page.append(advertisement)
    second_page = [_post(index) for index in range(19, 39)]
    weibo_upstream.add_page(1, first_page)
    weibo_upstream.add_page(2, second_page)

    user, posts = await fetch_user_feed_data(
        1842706721,
        25,
        sub_cookie="SUB=minimum",
        base_url=weibo_upstream.base_url,
    )

    assert user["screen_name"] == "微博测试用户"
    assert [post["idstr"] for post in posts] == [f"post-{index}" for index in range(25)]
    post_requests = [request for request in weibo_upstream.requests if request["path"] == "/ajax/statuses/mymblog"]
    assert [request["page"] for request in post_requests] == ["1", "2"]
    assert all(request["uid"] == "1842706721" for request in post_requests)
    assert all(request["feature"] == "0" for request in post_requests)
    assert all(request["cookie"] == "SUB=minimum" for request in weibo_upstream.requests)
    assert all(request["xsrf"] is None for request in weibo_upstream.requests)


@pytest.mark.asyncio
async def test_fetch_user_feed_expands_long_text_and_falls_back_on_failure(
    weibo_upstream: LocalWeiboUpstream,
) -> None:
    expanded = _post(1, is_long_text=True)
    fallback = _post(2, is_long_text=True)
    fallback["text_raw"] = "List fallback"
    weibo_upstream.add_page(1, [expanded, fallback])
    weibo_upstream.add_long_text(
        "Mblog1",
        {"ok": 1, "data": {"longTextContent": "<p>Expanded <strong>long text</strong></p>"}},
    )
    weibo_upstream.add_long_text("Mblog2", "upstream failure", status_code=500)

    _, posts = await fetch_user_feed_data(
        1842706721,
        12,
        sub_cookie="SUB=minimum",
        base_url=weibo_upstream.base_url,
    )

    assert "Expanded" in posts[0]["text_raw"]
    assert "long text" in posts[0]["text_raw"]
    assert posts[1]["text_raw"] == "List fallback"
    long_text_requests = [
        request for request in weibo_upstream.requests if request["path"] == "/ajax/statuses/longtext"
    ]
    assert [request["post_id"] for request in long_text_requests] == ["Mblog1", "Mblog2"]


@pytest.mark.asyncio
@pytest.mark.parametrize(
    ("status_code", "body", "expected_status"),
    [
        (404, "not found", 404),
        (429, "limited", 429),
        (432, "rejected", 429),
        (200, {"ok": -100, "data": {}}, 401),
        (200, "not json", 502),
        (200, {"ok": 1, "data": {}}, 502),
    ],
)
async def test_fetch_user_feed_maps_profile_errors(
    weibo_upstream: LocalWeiboUpstream,
    status_code: int,
    body: Any,
    expected_status: int,
) -> None:
    weibo_upstream.profile_response = (status_code, body, 0.0)

    with pytest.raises(HTTPException) as exc_info:
        await fetch_user_feed_data(
            1842706721,
            12,
            sub_cookie="SUB=minimum",
            base_url=weibo_upstream.base_url,
        )

    assert exc_info.value.status_code == expected_status


@pytest.mark.asyncio
async def test_fetch_user_feed_maps_timeout(weibo_upstream: LocalWeiboUpstream) -> None:
    weibo_upstream.profile_response = (200, _profile_payload(), 0.1)

    with pytest.raises(HTTPException) as exc_info:
        await fetch_user_feed_data(
            1842706721,
            12,
            sub_cookie="SUB=minimum",
            base_url=weibo_upstream.base_url,
            timeout=0.01,
        )

    assert exc_info.value.status_code == 504


def test_post_to_jsonfeed_item_renders_global_media_before_collapsible_text() -> None:
    post = _post(1)
    post["text_raw"] = "<Outer text>\nsecond line"
    post["pic_ids"] = ["outer-image", "live-image"]
    post["pic_infos"] = {
        "outer-image": {"largest": {"url": "https://cdn.example/outer.jpg"}},
        "live-image": {
            "largest": {"url": "https://cdn.example/live-poster.jpg"},
            "videoSrc": "https://cdn.example/live.mp4",
        },
    }
    post["page_info"] = {
        "page_pic": {"url": "https://cdn.example/outer-video-poster.jpg"},
        "urls": {"mp4_720p_mp4": "https://cdn.example/outer-video.mp4"},
    }
    repost = _post(2)
    repost["text_raw"] = "Original text"
    repost["pic_infos"] = {"repost-image": {"largest": {"url": "https://cdn.example/repost.jpg"}}}
    repost["pic_ids"] = ["repost-image"]
    repost["page_info"] = {
        "page_pic": {"url": "https://cdn.example/repost-video-poster.jpg"},
        "urls": {"mp4_hd_mp4": "https://cdn.example/repost-video.mp4"},
    }
    post["retweeted_status"] = repost

    item = post_to_jsonfeed_item(post, _user(), 1842706721)

    content_html = item.content_html or ""
    assert content_html.index("outer.jpg") < content_html.index("live-poster.jpg") < content_html.index("repost.jpg")
    assert (
        content_html.index("live.mp4") < content_html.index("outer-video.mp4") < content_html.index("repost-video.mp4")
    )
    assert content_html.index("repost.jpg") < content_html.index("live.mp4") < content_html.index("<details>")
    assert "&lt;Outer text&gt;<br>second line" in content_html
    assert "转发 @微博测试用户" in content_html
    assert item.attachments and [str(attachment.url) for attachment in item.attachments] == [
        "https://cdn.example/live.mp4",
        "https://cdn.example/outer-video.mp4",
        "https://cdn.example/repost-video.mp4",
    ]
    assert item.image and str(item.image) == "https://cdn.example/outer.jpg"


def test_post_to_jsonfeed_item_skips_invalid_media_urls() -> None:
    post = _post(1)
    post["pic_infos"] = {"bad-image": {"largest": {"url": "javascript:alert(1)"}}}
    post["pic_ids"] = ["bad-image"]
    post["page_info"] = {"urls": {"mp4_720p_mp4": "not-a-url"}}
    post["user"]["avatar_hd"] = "data:text/html,unsafe"

    item = post_to_jsonfeed_item(post, _user(), 1842706721)

    assert "javascript:" not in (item.content_html or "")
    assert "not-a-url" not in (item.content_html or "")
    assert item.image is None
    assert item.attachments is None
    assert item.author and item.author.avatar is None


def test_build_user_feed_hides_cookie_query_parameter() -> None:
    feed = build_user_feed(_request(b"max_posts=12&cookies=SUB%3Dsecret"), 1842706721, _user(), [_post(1)])

    assert feed.title == "微博测试用户 (@1842706721) 的微博"
    assert feed.feed_url and "cookies=" not in str(feed.feed_url)
    assert feed.author and feed.author.avatar == "https://cdn.example/avatar.jpg"


def test_weibo_route_requires_sub_cookie() -> None:
    with TestClient(app) as client:
        no_cookie_response = client.get("/api/rss/weibo/1842706721/posts")
        invalid_cookie_response = client.get(
            "/api/rss/weibo/1842706721/posts",
            headers={"X-Weibo-Cookie": "XSRF-TOKEN=not-enough"},
        )
        openapi = client.get("/openapi.json").json()

    assert no_cookie_response.status_code == 401
    assert invalid_cookie_response.status_code == 401
    parameters = openapi["paths"]["/api/rss/weibo/{uid}/posts"]["get"]["parameters"]
    max_posts = next(parameter for parameter in parameters if parameter["name"] == "max_posts")
    assert max_posts["schema"]["default"] == 20
