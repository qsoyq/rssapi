import asyncio
import json
import threading
import time
from collections.abc import Iterator
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from typing import Any
from urllib.parse import parse_qs, urlparse

import pytest
from fastapi import HTTPException, Request
from fastapi.testclient import TestClient
from playwright.async_api import async_playwright

from rssapi.applications.tiktok.browser import (
    TikTokBrowserError,
    _cookies_from_header,
    _payload_items,
    _playwright_proxy,
    clear_v2_cache,
    fetch_user_posts_v2,
    fetch_user_posts_v2_by_cache,
    v2_inflight_count,
)
from rssapi.applications.tiktok.router import (
    _feed_item_v2,
    _feed_url_without_cookie,
    _resolve_tiktok_cookie,
)
from rssapi.main import app


def _user(
    username: str = "arimariash",
    *,
    private: bool = False,
    include_privacy: bool = True,
) -> dict[str, Any]:
    user: dict[str, Any] = {
        "id": "1234567890",
        "secUid": "MS4wLjABAAAA-test-sec-uid",
        "uniqueId": username,
        "nickname": "Ari",
        "avatarLarger": {"urlList": ["https://cdn.example/avatar.jpg"]},
    }
    if include_privacy:
        user["privateAccount"] = private
        user["secret"] = False
    return user


def _post(index: int, username: str = "arimariash", *, private: bool = False) -> dict[str, Any]:
    return {
        "id": str(7_600_000_000_000_000_000 + index),
        "desc": f"Video {index}",
        "createTime": 1_700_000_000 + index,
        "author": _user(username, private=private),
        "video": {
            "playAddr": {"urlList": [f"https://cdn.example/video-{index}.mp4"]},
            "cover": {"urlList": [f"https://cdn.example/cover-{index}.jpg"]},
        },
    }


class LocalTikTokBrowserUpstream:
    def __init__(self, *, mode: str = "posts") -> None:
        self.mode = mode
        self.requests: list[str] = []
        self.cookie_headers: list[str | None] = []
        controller = self

        class Handler(BaseHTTPRequestHandler):
            def do_GET(self) -> None:
                parsed = urlparse(self.path)
                path = parsed.path
                query = parse_qs(parsed.query)
                controller.requests.append(path)
                if path.startswith("/@"):
                    controller.cookie_headers.append(self.headers.get("Cookie"))
                    cookie = self.headers.get("Cookie") or ""
                    if (
                        controller.mode == "challenge"
                        or (controller.mode == "requires_cookie" and not self.headers.get("Cookie"))
                        or (controller.mode == "cookie_challenge" and "blocked=1" in cookie)
                    ):
                        self._send_html("<html><body>Drag the slider to fit the puzzle</body></html>")
                        return
                    first_path = "/api/post/item_list/" if controller.mode == "empty" else "/api/user/detail/"
                    second_path = "/api/user/detail/" if controller.mode == "empty" else "/api/post/item_list/"
                    username = path.removeprefix("/@") or "arimariash"
                    delay = 1200 if controller.mode == "slow" else 0
                    body = f"""
                        <html><body>Profile loaded<script>
                        setTimeout(() => fetch('{first_path}?username={username}')
                            .then(() => fetch('{second_path}?username={username}')), {delay});
                        </script></body></html>
                    """
                    self._send_html(body)
                    return
                username = query.get("username", ["arimariash"])[0]
                private = controller.mode == "private"
                include_privacy = controller.mode != "missing_privacy"
                if path == "/api/user/detail/":
                    user = _user(username, private=private, include_privacy=include_privacy)
                    if controller.mode == "missing_private_account":
                        user.pop("privateAccount", None)
                    if controller.mode == "missing_secret":
                        user.pop("secret", None)
                    self._send_json(
                        {
                            "statusCode": 0,
                            "userInfo": {"user": user},
                        }
                    )
                    return
                if path == "/api/post/item_list/":
                    if controller.mode == "hanging_body":
                        self.send_response(200)
                        self.send_header("Content-Type", "application/json")
                        self.send_header("Content-Length", "4096")
                        self.end_headers()
                        time.sleep(3)
                        return
                    posts = (
                        []
                        if controller.mode == "empty"
                        else [
                            _post(1, username, private=private),
                            _post(2, username, private=private),
                        ]
                    )
                    if not include_privacy:
                        for post in posts:
                            post["author"].pop("privateAccount", None)
                            post["author"].pop("secret", None)
                    if controller.mode == "missing_private_account":
                        for post in posts:
                            post["author"].pop("privateAccount", None)
                    if controller.mode == "missing_secret":
                        for post in posts:
                            post["author"].pop("secret", None)
                    self._send_json({"statusCode": 0, "itemList": posts, "hasMore": False})
                    return
                self._send_json({"statusCode": 404}, status_code=404)

            def _send_html(self, body: str) -> None:
                payload = body.encode()
                self.send_response(200)
                self.send_header("Content-Type", "text/html; charset=utf-8")
                self.send_header("Content-Length", str(len(payload)))
                self.end_headers()
                self.wfile.write(payload)

            def _send_json(self, body: dict[str, Any], *, status_code: int = 200) -> None:
                payload = json.dumps(body).encode()
                self.send_response(status_code)
                self.send_header("Content-Type", "application/json")
                self.send_header("Content-Length", str(len(payload)))
                self.end_headers()
                self.wfile.write(payload)

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
def browser_upstream() -> Iterator[LocalTikTokBrowserUpstream]:
    upstream = LocalTikTokBrowserUpstream()
    upstream.start()
    try:
        yield upstream
    finally:
        upstream.close()


async def _require_chromium() -> None:
    async with async_playwright() as playwright:
        if not Path(playwright.chromium.executable_path).is_file():
            pytest.skip("Playwright Chromium is not installed")


def _request(*, client_host: str = "127.0.0.1", query_string: bytes = b"") -> Request:
    return Request(
        {
            "type": "http",
            "http_version": "1.1",
            "method": "GET",
            "scheme": "http",
            "path": "/api/rss/tiktok/v2/arimariash/posts",
            "raw_path": b"/api/rss/tiktok/v2/arimariash/posts",
            "query_string": query_string,
            "headers": [],
            "client": (client_host, 50000),
            "server": ("testserver", 80),
        }
    )


@pytest.mark.asyncio
async def test_playwright_fetches_posts_and_collapses_concurrent_cache_misses(
    browser_upstream: LocalTikTokBrowserUpstream,
) -> None:
    await _require_chromium()
    await clear_v2_cache()

    first, second = await asyncio.gather(
        fetch_user_posts_v2_by_cache(
            "@arimariash",
            2,
            base_url=browser_upstream.base_url,
            timeout=10,
        ),
        fetch_user_posts_v2_by_cache(
            "arimariash",
            2,
            base_url=browser_upstream.base_url,
            timeout=10,
        ),
    )

    assert first == second
    user, posts = first
    assert user["uniqueId"] == "arimariash"
    assert [post["id"] for post in posts] == ["7600000000000000001", "7600000000000000002"]
    assert browser_upstream.requests.count("/@arimariash") == 1


@pytest.mark.asyncio
async def test_playwright_accepts_verified_empty_posts_when_profile_response_arrives_last() -> None:
    await _require_chromium()
    upstream = LocalTikTokBrowserUpstream(mode="empty")
    upstream.start()
    try:
        user, posts = await fetch_user_posts_v2("arimariash", 12, base_url=upstream.base_url, timeout=10)
    finally:
        upstream.close()

    assert user["uniqueId"] == "arimariash"
    assert posts == []


@pytest.mark.asyncio
async def test_playwright_reports_challenge_instead_of_empty_feed() -> None:
    await _require_chromium()
    upstream = LocalTikTokBrowserUpstream(mode="challenge")
    upstream.start()
    try:
        with pytest.raises(TikTokBrowserError) as exc_info:
            await fetch_user_posts_v2("arimariash", 12, base_url=upstream.base_url, timeout=10)
    finally:
        upstream.close()

    assert exc_info.value.kind == "challenge"
    assert exc_info.value.status_code == 503


@pytest.mark.asyncio
async def test_cookie_header_bootstraps_browser_and_cached_result_no_longer_requires_cookie() -> None:
    await _require_chromium()
    await clear_v2_cache()
    upstream = LocalTikTokBrowserUpstream(mode="requires_cookie")
    upstream.start()
    try:
        authenticated = await fetch_user_posts_v2_by_cache(
            "arimariash",
            2,
            base_url=upstream.base_url,
            timeout=10,
            cookie_header="session=abc==; theme=dark",
        )
        cached = await fetch_user_posts_v2_by_cache(
            "arimariash",
            2,
            base_url=upstream.base_url,
            timeout=10,
        )
    finally:
        upstream.close()

    assert authenticated == cached
    assert upstream.requests.count("/@arimariash") == 1
    assert upstream.cookie_headers == ["session=abc==; theme=dark"]


@pytest.mark.asyncio
async def test_private_profile_is_rejected_and_never_enters_public_cache() -> None:
    await _require_chromium()
    await clear_v2_cache()
    upstream = LocalTikTokBrowserUpstream(mode="private")
    upstream.start()
    try:
        with pytest.raises(TikTokBrowserError) as exc_info:
            await fetch_user_posts_v2_by_cache(
                "arimariash",
                2,
                base_url=upstream.base_url,
                timeout=10,
                cookie_header="session=authorized",
            )
        upstream.mode = "posts"
        _, posts = await fetch_user_posts_v2_by_cache(
            "arimariash",
            2,
            base_url=upstream.base_url,
            timeout=10,
        )
    finally:
        upstream.close()

    assert exc_info.value.kind == "private"
    assert exc_info.value.status_code == 403
    assert len(posts) == 2
    assert upstream.requests.count("/@arimariash") == 2


@pytest.mark.asyncio
async def test_failure_cache_is_isolated_by_cookie_fingerprint() -> None:
    await _require_chromium()
    await clear_v2_cache()
    upstream = LocalTikTokBrowserUpstream(mode="cookie_challenge")
    upstream.start()
    try:
        with pytest.raises(TikTokBrowserError) as exc_info:
            await fetch_user_posts_v2_by_cache(
                "arimariash",
                2,
                base_url=upstream.base_url,
                timeout=10,
                cookie_header="blocked=1",
            )
        _, posts = await fetch_user_posts_v2_by_cache(
            "arimariash",
            2,
            base_url=upstream.base_url,
            timeout=10,
            cookie_header="session=valid",
        )
    finally:
        upstream.close()

    assert exc_info.value.kind == "challenge"
    assert len(posts) == 2


@pytest.mark.asyncio
@pytest.mark.parametrize("mode", ["missing_privacy", "missing_private_account", "missing_secret"])
async def test_missing_privacy_state_fails_closed(mode: str) -> None:
    await _require_chromium()
    upstream = LocalTikTokBrowserUpstream(mode=mode)
    upstream.start()
    try:
        with pytest.raises(TikTokBrowserError) as exc_info:
            await fetch_user_posts_v2("arimariash", 2, base_url=upstream.base_url, timeout=10)
    finally:
        upstream.close()

    assert exc_info.value.kind == "invalid_payload"
    assert exc_info.value.status_code == 502


@pytest.mark.asyncio
async def test_timeout_cancels_hanging_response_body_capture() -> None:
    await _require_chromium()
    upstream = LocalTikTokBrowserUpstream(mode="hanging_body")
    upstream.start()
    started_at = asyncio.get_running_loop().time()
    try:
        with pytest.raises(TikTokBrowserError) as exc_info:
            await fetch_user_posts_v2("arimariash", 2, base_url=upstream.base_url, timeout=0.8)
        elapsed = asyncio.get_running_loop().time() - started_at
    finally:
        upstream.close()

    assert exc_info.value.kind == "timeout"
    assert elapsed < 4


@pytest.mark.asyncio
async def test_browser_inflight_limit_rejects_excess_unique_requests() -> None:
    await _require_chromium()
    await clear_v2_cache()
    upstream = LocalTikTokBrowserUpstream(mode="slow")
    upstream.start()
    tasks = [
        asyncio.create_task(
            fetch_user_posts_v2_by_cache(
                "arimariash",
                2,
                base_url=upstream.base_url,
                timeout=8,
                cookie_header=f"session={index}",
            )
        )
        for index in range(3)
    ]
    try:
        deadline = asyncio.get_running_loop().time() + 2
        while await v2_inflight_count() < 3 and asyncio.get_running_loop().time() < deadline:
            await asyncio.sleep(0.01)
        with pytest.raises(TikTokBrowserError) as exc_info:
            await fetch_user_posts_v2_by_cache(
                "arimariash",
                2,
                base_url=upstream.base_url,
                timeout=8,
                cookie_header="session=overflow",
            )
        await asyncio.gather(*tasks)
    finally:
        upstream.close()

    assert exc_info.value.kind == "busy"
    assert exc_info.value.status_code == 503
    assert await v2_inflight_count() == 0


@pytest.mark.asyncio
async def test_cancelled_waiter_does_not_leave_completed_inflight_task() -> None:
    await _require_chromium()
    await clear_v2_cache()
    upstream = LocalTikTokBrowserUpstream(mode="slow")
    upstream.start()
    waiter = asyncio.create_task(
        fetch_user_posts_v2_by_cache(
            "arimariash",
            2,
            base_url=upstream.base_url,
            timeout=8,
            cookie_header="session=cancelled-waiter",
        )
    )
    try:
        deadline = asyncio.get_running_loop().time() + 2
        while await v2_inflight_count() < 1 and asyncio.get_running_loop().time() < deadline:
            await asyncio.sleep(0.01)
        waiter.cancel()
        with pytest.raises(asyncio.CancelledError):
            await waiter
        deadline = asyncio.get_running_loop().time() + 4
        while await v2_inflight_count() and asyncio.get_running_loop().time() < deadline:
            await asyncio.sleep(0.05)
    finally:
        upstream.close()

    assert await v2_inflight_count() == 0


@pytest.mark.asyncio
async def test_browser_timeout_includes_waiting_for_concurrency_slot() -> None:
    await _require_chromium()
    upstream = LocalTikTokBrowserUpstream(mode="slow")
    upstream.start()
    blocker = asyncio.create_task(fetch_user_posts_v2("arimariash", 2, base_url=upstream.base_url, timeout=5))
    try:
        deadline = asyncio.get_running_loop().time() + 2
        while "/@arimariash" not in upstream.requests and asyncio.get_running_loop().time() < deadline:
            await asyncio.sleep(0.01)
        started_at = asyncio.get_running_loop().time()
        with pytest.raises(TikTokBrowserError) as exc_info:
            await fetch_user_posts_v2("anotheruser", 2, base_url=upstream.base_url, timeout=0.5)
        elapsed = asyncio.get_running_loop().time() - started_at
        await blocker
    finally:
        upstream.close()

    assert elapsed < 0.8
    assert exc_info.value.kind == "timeout"


def test_payload_filter_rejects_unrelated_prefetch_items() -> None:
    payload = {"itemList": [_post(1, "someone_else")]}

    assert _payload_items(payload, "arimariash") is None


def test_cookie_header_parser_preserves_equals_in_value() -> None:
    cookies = _cookies_from_header("session=abc==; empty=", "https://www.tiktok.com")

    assert cookies == [
        {
            "name": "session",
            "value": "abc==",
            "domain": ".tiktok.com",
            "path": "/",
            "secure": True,
            "sameSite": "Lax",
        },
        {
            "name": "empty",
            "value": "",
            "domain": ".tiktok.com",
            "path": "/",
            "secure": True,
            "sameSite": "Lax",
        },
    ]


def test_cookie_header_takes_precedence_over_query() -> None:
    assert _resolve_tiktok_cookie(_request(), "query=value", "header=value", query_enabled=True) == "header=value"
    assert _resolve_tiktok_cookie(_request(), "query=value", "header=value", query_enabled=False) == "header=value"
    assert _resolve_tiktok_cookie(_request(client_host="203.0.113.1"), None, "header=value") == "header=value"


def test_cookie_query_requires_explicit_enablement_but_allows_remote_clients() -> None:
    with pytest.raises(HTTPException) as disabled_exc:
        _resolve_tiktok_cookie(_request(), "query=value", None, query_enabled=False)

    assert getattr(disabled_exc.value, "status_code", None) == 403
    assert _resolve_tiktok_cookie(_request(), "query=value", None, query_enabled=True) == "query=value"
    assert (
        _resolve_tiktok_cookie(_request(client_host="203.0.113.1"), "query=value", None, query_enabled=True)
        == "query=value"
    )


def test_tiktok_cookie_is_required() -> None:
    with pytest.raises(HTTPException) as exc_info:
        _resolve_tiktok_cookie(_request(), None, None)

    assert getattr(exc_info.value, "status_code", None) == 400
    assert getattr(exc_info.value, "detail", None) == "TikTok Cookie is required"


def test_proxy_configuration_separates_credentials() -> None:
    assert _playwright_proxy("http://user:p%40ss@proxy.example:8080") == {
        "server": "http://proxy.example:8080",
        "username": "user",
        "password": "p@ss",
    }


def test_proxy_configuration_rejects_invalid_port() -> None:
    with pytest.raises(TikTokBrowserError) as exc_info:
        _playwright_proxy("http://proxy.example:not-a-port")

    assert exc_info.value.kind == "configuration"
    assert exc_info.value.status_code == 503


def test_v2_feed_item_uses_direct_media_by_default() -> None:
    item = _feed_item_v2(_request(), _post(1), _user(), "arimariash", 12)

    assert item.attachments
    assert str(item.attachments[0].url) == "https://cdn.example/video-1.mp4"


def test_v2_feed_item_uses_proxy_media_when_configured() -> None:
    item = _feed_item_v2(_request(), _post(1), _user(), "arimariash", 12, media_mode="proxy")

    assert item.attachments
    assert str(item.attachments[0].url).startswith(
        "http://testserver/api/rss/tiktok/v2/media/arimariash/7600000000000000001"
    )


def test_v2_feed_url_does_not_echo_cookie_query() -> None:
    request = _request(query_string=b"max_posts=12&cookies=session%3Dsecret")

    feed_url = _feed_url_without_cookie(request)

    assert feed_url == "http://testserver/api/rss/tiktok/v2/arimariash/posts?max_posts=12"
    assert "secret" not in feed_url


def test_tiktok_v2_route_requires_cookie() -> None:
    with TestClient(app) as client:
        response = client.get("/api/rss/tiktok/v2/rako_bear_/posts")

    assert response.status_code == 400
    assert response.json() == {"detail": "TikTok Cookie is required"}


@pytest.mark.parametrize("username", ["bad-name", "@bad-name", "a" * 25])
def test_tiktok_v2_route_rejects_invalid_username(username: str) -> None:
    with TestClient(app) as client:
        response = client.get(f"/api/rss/tiktok/v2/{username}/posts")

    assert response.status_code == 422
