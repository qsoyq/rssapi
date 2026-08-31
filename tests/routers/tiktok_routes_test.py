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

from rssapi.applications.tiktok.router import _validated_range, proxy_media_response
from rssapi.applications.tiktok.utils import (
    fetch_posts_by_sec_uid,
    fetch_user_posts,
    normalize_username,
    post_to_jsonfeed_item,
)
from rssapi.core.settings import settings
from rssapi.main import app
from rssapi.utils.cache import RandomTTLCache


def _user(username: str = "arimariash", *, private: bool = False) -> dict[str, Any]:
    return {
        "id": "1234567890",
        "secUid": "MS4wLjABAAAA-test-sec-uid",
        "uniqueId": username,
        "nickname": "Ari",
        "privateAccount": private,
        "avatarLarger": {"urlList": ["https://cdn.example/avatar.jpg"]},
    }


def _video_post(index: int, username: str = "arimariash") -> dict[str, Any]:
    return {
        "id": str(7_600_000_000_000_000_000 + index),
        "desc": f"Video {index}\n#travel",
        "createTime": 1_700_000_000 + index,
        "author": _user(username),
        "video": {
            "playAddr": {"urlList": [f"https://cdn.example/video-{index}.mp4?x=1&y=2"]},
            "cover": {"urlList": [f"https://cdn.example/cover-{index}.jpg"]},
            "bitrateInfo": [
                {
                    "PlayAddr": {
                        "UrlList": [
                            f"https://v19-webapp-prime.tiktok.com/video-{index}.mp4",
                            f"https://www.tiktok.com/aweme/v1/play/?video_id=video-{index}",
                        ]
                    }
                }
            ],
        },
        "stats": {"diggCount": index, "commentCount": index + 1, "shareCount": 2, "playCount": 100},
        "textExtra": [{"hashtagName": "travel"}],
    }


def _image_post(index: int, username: str = "arimariash") -> dict[str, Any]:
    post = _video_post(index, username)
    post.pop("video")
    post["imagePost"] = {
        "images": [
            {"imageURL": {"urlList": [f"https://cdn.example/image-{index}-1.jpg"]}},
            {"imageURL": {"urlList": [f"https://cdn.example/image-{index}-2.jpg"]}},
        ]
    }
    return post


class LocalTikTokUpstream:
    def __init__(self, *, mode: str = "ok", delay: float = 0.0) -> None:
        self.mode = mode
        self.delay = delay
        self.requests: list[dict[str, Any]] = []
        controller = self

        class Handler(BaseHTTPRequestHandler):
            def do_GET(self) -> None:
                parsed = urlparse(self.path)
                query = parse_qs(parsed.query)
                controller.requests.append(
                    {
                        "path": parsed.path,
                        "query": query,
                        "cookie": self.headers.get("Cookie"),
                        "range": self.headers.get("Range"),
                        "referer": self.headers.get("Referer"),
                    }
                )
                if controller.delay:
                    time.sleep(controller.delay)
                if parsed.path == "/media/video.mp4":
                    payload = b"\x00\x00\x00\x18ftypisom" + bytes(4084)
                    self.send_response(206 if self.headers.get("Range") else 200)
                    self.send_header("Content-Type", "video/mp4")
                    self.send_header("Accept-Ranges", "bytes")
                    self.send_header("Content-Length", str(len(payload)))
                    if self.headers.get("Range"):
                        self.send_header("Content-Range", f"bytes 0-{len(payload) - 1}/{len(payload)}")
                    self.end_headers()
                    self.wfile.write(payload)
                    return
                if parsed.path.startswith("/@"):
                    if controller.mode == "rate_limit":
                        self._send(429, {"error": "rate limited"})
                        return
                    self.send_response(200)
                    if controller.mode == "missing_hydration":
                        body = b"<html>risk control shell</html>"
                        self.send_header("Content-Type", "text/html")
                        self.send_header("Content-Length", str(len(body)))
                        self.end_headers()
                        self.wfile.write(body)
                        return
                    profile_data = {"LiveRoom": {"liveRoomUserInfo": {"user": _user()}}}
                    hydration = json.dumps(profile_data) if controller.mode != "missing_profile" else "{}"
                    body = (
                        f'<html><script id="SIGI_STATE" type="application/json">{hydration}</script></html>'.encode()
                    )
                    self.send_header("Content-Type", "text/html")
                    self.send_header("Content-Length", str(len(body)))
                    self.end_headers()
                    self.wfile.write(body)
                    return
                if controller.mode == "empty":
                    self.send_response(200)
                    self.send_header("Content-Type", "application/json")
                    self.send_header("Content-Length", "0")
                    self.end_headers()
                    return
                if parsed.path == "/api/creator/item_list/":
                    if controller.mode in ("inaccessible", "terminal_empty"):
                        self._send(
                            200,
                            {
                                "statusCode": 0,
                                "itemList": [],
                                "hasMorePrevious": controller.mode == "inaccessible",
                            },
                        )
                        return
                    cursor = query.get("cursor", [""])[0]
                    response_payload = (
                        {
                            "statusCode": 0,
                            "itemList": [_video_post(1), _video_post(2)],
                            "hasMorePrevious": True,
                        }
                        if int(cursor) > 1_700_000_002_000
                        else {"statusCode": 0, "itemList": [_image_post(3)], "hasMorePrevious": False}
                    )
                    self._send(200, response_payload)
                    return
                self._send(404, {"error": "not found"})

            def _send(self, status_code: int, body: Any) -> None:
                payload = json.dumps(body).encode()
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
        host = str(address[0])
        port = int(address[1])
        return f"http://{host}:{port}"

    def start(self) -> None:
        self.thread.start()

    def close(self) -> None:
        self.server.shutdown()
        self.server.server_close()
        self.thread.join()


@pytest.fixture
def tiktok_upstream() -> Iterator[LocalTikTokUpstream]:
    upstream = LocalTikTokUpstream()
    upstream.start()
    try:
        yield upstream
    finally:
        upstream.close()


@pytest.mark.parametrize(
    ("value", "expected"),
    [("arimariash", "arimariash"), ("@arimariash", "arimariash"), ("@Mixed.Case", "mixed.case")],
)
def test_normalize_username(value: str, expected: str) -> None:
    assert normalize_username(value) == expected


@pytest.mark.asyncio
async def test_fetch_user_posts_resolves_public_profile_and_paginates(tiktok_upstream: LocalTikTokUpstream) -> None:
    user, posts = await fetch_user_posts("@arimariash", 3, base_url=tiktok_upstream.base_url)

    assert user["nickname"] == "Ari"
    assert [post["id"] for post in posts] == [
        "7600000000000000001",
        "7600000000000000002",
        "7600000000000000003",
    ]
    api_requests = [request for request in tiktok_upstream.requests if request["path"].startswith("/api/")]
    assert len(api_requests) == 2
    assert all(request["query"].get("secUid") == ["MS4wLjABAAAA-test-sec-uid"] for request in api_requests)
    assert all(
        request["query"].get("count") == (["3"] if index == 0 else ["1"]) for index, request in enumerate(api_requests)
    )
    assert api_requests[1]["query"].get("cursor") == ["1700000001000"]


@pytest.mark.asyncio
@pytest.mark.parametrize(
    ("mode", "status_code"),
    [
        ("missing_profile", 404),
        ("missing_hydration", 502),
        ("empty", 502),
        ("rate_limit", 429),
        ("inaccessible", 403),
        ("terminal_empty", 403),
    ],
)
async def test_fetch_user_posts_maps_upstream_failures(mode: str, status_code: int) -> None:
    upstream = LocalTikTokUpstream(mode=mode)
    upstream.start()
    try:
        with pytest.raises(HTTPException) as exc_info:
            await fetch_user_posts("arimariash", 12, base_url=upstream.base_url)
    finally:
        upstream.close()

    assert exc_info.value.status_code == status_code
    expected_attempts = (
        1 if mode in ("missing_profile", "missing_hydration", "rate_limit", "inaccessible", "terminal_empty") else 2
    )
    assert len([request for request in upstream.requests if request["path"].startswith("/@")]) == expected_attempts


@pytest.mark.asyncio
async def test_fetch_user_posts_maps_timeout() -> None:
    upstream = LocalTikTokUpstream(delay=0.1)
    upstream.start()
    try:
        with pytest.raises(HTTPException) as exc_info:
            await fetch_user_posts("arimariash", 12, base_url=upstream.base_url, timeout=0.01)
    finally:
        upstream.close()

    assert exc_info.value.status_code == 504


def test_post_conversion_supports_video_and_image_posts() -> None:
    video_item = post_to_jsonfeed_item(_video_post(1), _user(), "arimariash")
    image_item = post_to_jsonfeed_item(_image_post(2), _user(), "arimariash")

    assert str(video_item.url).endswith("/@arimariash/video/7600000000000000001")
    assert video_item.attachments and video_item.attachments[0].mime_type == "video/mp4"
    assert str(video_item.attachments[0].url).startswith("https://www.tiktok.com/aweme/v1/play/")
    assert video_item.content_html and "<video controls" in video_item.content_html
    assert video_item.tags == ["travel"]
    assert image_item.attachments and len(image_item.attachments) == 2
    assert all(attachment.mime_type == "image/jpeg" for attachment in image_item.attachments)
    assert image_item.content_html and image_item.content_html.count("<img ") == 2


def test_post_conversion_uses_media_proxy_url() -> None:
    media_url = (
        "http://testserver/api/rss/tiktok/media/arimariash/7600000000000000001"
        "?sec_uid=MS4wLjABAAAA-test-sec-uid&max_posts=12"
    )
    item = post_to_jsonfeed_item(_video_post(1), _user(), "arimariash", media_url=media_url)

    assert item.attachments and str(item.attachments[0].url) == media_url
    assert item.content_html and f'src="{media_url.replace("&", "&amp;")}"' in item.content_html


@pytest.mark.asyncio
async def test_media_proxy_forwards_range_and_tiktok_referer(tiktok_upstream: LocalTikTokUpstream) -> None:
    referer = "https://www.tiktok.com/@arimariash/video/7600000000000000001"
    response = await proxy_media_response(
        f"{tiktok_upstream.base_url}/media/video.mp4",
        referer,
        "bytes=0-4095",
        allowed_hosts=("127.0.0.1",),
    )
    body_parts: list[bytes] = []
    async for chunk in response.body_iterator:
        body_parts.append(chunk.encode() if isinstance(chunk, str) else bytes(chunk))
    body = b"".join(body_parts)

    assert response.status_code == 206
    assert response.media_type == "video/mp4"
    assert response.headers["content-range"] == "bytes 0-4095/4096"
    assert b"ftyp" in body[:16]
    media_request = next(request for request in tiktok_upstream.requests if request["path"] == "/media/video.mp4")
    assert media_request["range"] == "bytes=0-4095"
    assert media_request["referer"] == referer


@pytest.mark.asyncio
async def test_media_resolution_by_sec_uid_does_not_fetch_profile(tiktok_upstream: LocalTikTokUpstream) -> None:
    posts = await fetch_posts_by_sec_uid(
        "arimariash",
        "MS4wLjABAAAA-test-sec-uid",
        3,
        base_url=tiktok_upstream.base_url,
    )

    assert len(posts) == 3
    assert not any(request["path"].startswith("/@") for request in tiktok_upstream.requests)


@pytest.mark.parametrize("value", ["bytes=0-1,4-5", "items=0-10", "bytes=20-10", "bytes=0-20000000"])
def test_media_proxy_rejects_invalid_or_oversized_ranges(value: str) -> None:
    with pytest.raises(HTTPException) as exc_info:
        _validated_range(value)
    assert exc_info.value.status_code == 416


def test_tiktok_cache_defaults_to_dynamic_three_to_six_hours() -> None:
    assert settings.tiktok.user_posts_cache_ttl == 10800
    cache = RandomTTLCache(maxsize=1, ttl=settings.tiktok.user_posts_cache_ttl)
    started_at = cache.timer()
    cache["key"] = "value"
    links = getattr(cache, "_RandomTTLCache__links")
    link = links["key"]
    assert started_at + 10800 <= link.expires <= started_at + 21600


@pytest.mark.parametrize("username", ["bad-name", "@bad-name", "a" * 25, "@" + "a" * 25])
def test_tiktok_route_rejects_invalid_username(username: str) -> None:
    with TestClient(app) as client:
        response = client.get(f"/api/rss/tiktok/{username}/posts")
    assert response.status_code == 422


@pytest.mark.parametrize("max_posts", [0, 51])
def test_tiktok_route_validates_max_posts(max_posts: int) -> None:
    with TestClient(app) as client:
        response = client.get("/api/rss/tiktok/arimariash/posts", params={"max_posts": max_posts})
    assert response.status_code == 422


@pytest.mark.parametrize(
    "path",
    [
        "/api/rss/tiktok/media/@arimariash/7600000000000000001",
        "/api/rss/tiktok/media/bad-name/7600000000000000001",
        "/api/rss/tiktok/media/arimariash/not-a-video-id",
    ],
)
def test_tiktok_media_route_rejects_invalid_identifiers(path: str) -> None:
    with TestClient(app) as client:
        response = client.get(path)
    assert response.status_code == 422
