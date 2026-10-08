import asyncio
import json
import threading
import time
from collections.abc import Iterator
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from urllib.parse import parse_qs, urlsplit

import httpx
import pytest
from tests.routers.douyin_routes_test import post

from rssapi.applications.douyin.router import (
    fetch_topic_feeds,
    fetch_topic_feeds_by_cache,
    topic_feeds_cache,
)
from rssapi.applications.douyin.search import (
    SEARCH_PATH,
    DouyinSearchError,
    DouyinTopicClient,
    httpx_proxy,
    search_payload,
)
from rssapi.applications.douyin.utils import parse_cookies
from rssapi.utils.playwright_capacity import (
    PlaywrightCapacityError,
    _playwright_capacity_limiter,
    acquire_playwright_slot,
)


class LocalDouyinUpstream:
    def __init__(self) -> None:
        self.mode = "posts"
        self.search_requests: list[dict] = []
        self.homepage_requests = 0
        self.homepage_headers: list[dict[str, str]] = []
        self.user_agents: list[str] = []
        controller = self

        class Handler(BaseHTTPRequestHandler):
            def do_GET(self) -> None:
                parsed = urlsplit(self.path)
                if parsed.path == "/":
                    controller.homepage_requests += 1
                    controller.homepage_headers.append(dict(self.headers))
                    controller.user_agents.append(self.headers.get("User-Agent", ""))
                    body = (
                        "<html><title>Douyin integration test</title><script>"
                        'localStorage.setItem("xmst", "runtime-token==");</script>'
                        + (
                            '<div id="captcha_container">Verify</div>'
                            if controller.mode == "bootstrap_challenge"
                            else ""
                        )
                        + "</html>"
                    ).encode()
                    self.send_response(200)
                    self.send_header("Content-Type", "text/html")
                    self.send_header("Set-Cookie", "UIFID_TEMP=runtime-fingerprint; Path=/")
                    self.send_header("Content-Length", str(len(body)))
                    self.end_headers()
                    self.wfile.write(body)
                    return
                if parsed.path != SEARCH_PATH:
                    self.send_error(404)
                    return
                query = parse_qs(parsed.query, keep_blank_values=True)
                controller.search_requests.append({"query": query, "headers": dict(self.headers)})
                offset = int(query["offset"][0])
                if controller.mode == "slow":
                    time.sleep(1)
                if controller.mode in ("challenge", "later_challenge", "third_page_challenge") and (
                    controller.mode == "challenge"
                    or (controller.mode == "later_challenge" and offset > 0)
                    or (controller.mode == "third_page_challenge" and offset >= 30)
                ):
                    payload = {"status_code": 0, "data": [], "search_nil_info": {"search_nil_type": "verify_check"}}
                elif controller.mode == "empty_body":
                    self._send(b"")
                    return
                elif controller.mode == "empty_feed":
                    payload = {"status_code": 0, "data": [], "has_more": 0}
                elif controller.mode == "logged_out":
                    payload = {"status_code": 2483, "status_msg": "请先登录"}
                else:
                    if offset == 0:
                        entries = [post(1), post(2), post(9, hashtag="示例话题其他")]
                    elif offset == 15:
                        gallery = post(3, timestamp=1_700_000_100)
                        gallery["images"] = [{"url_list": ["https://cdn.example/1.jpg", "https://cdn.example/2.jpg"]}]
                        gallery["video"] = None
                        entries = [post(2), gallery]
                    else:
                        entries = [post(4, timestamp=1_699_999_900)]
                    payload = {
                        "status_code": 0,
                        "data": [{"type": 1, "aweme_info": item} for item in entries] + [{"type": 6}],
                        "cursor": 0 if controller.mode == "stuck_cursor" else offset + 15,
                        "has_more": 0 if controller.mode == "early_end" else 1,
                        "log_pb": {} if controller.mode == "missing_search_id" else {"impr_id": "search-session"},
                    }
                self._send(json.dumps(payload, ensure_ascii=False).encode())

            def _send(self, body: bytes) -> None:
                self.send_response(200)
                self.send_header("Content-Type", "application/json")
                self.send_header("Content-Length", str(len(body)))
                self.end_headers()
                try:
                    self.wfile.write(body)
                except BrokenPipeError:
                    pass

            def log_message(self, format: str, *args: object) -> None:
                return

        self.server = ThreadingHTTPServer(("127.0.0.1", 0), Handler)
        self.thread = threading.Thread(target=self.server.serve_forever, daemon=True)

    @property
    def base_url(self) -> str:
        return f"http://127.0.0.1:{self.server.server_address[1]}"

    def client(self) -> DouyinTopicClient:
        return DouyinTopicClient(self.base_url, startup_wait=0, page_delay=0, environment={})


@pytest.fixture
def upstream() -> Iterator[LocalDouyinUpstream]:
    from playwright.async_api import async_playwright

    async def chromium_installed() -> bool:
        async with async_playwright() as playwright:
            return Path(playwright.chromium.executable_path).is_file()

    if not asyncio.run(chromium_installed()):
        pytest.skip("Playwright Chromium is not installed")
    server = LocalDouyinUpstream()
    topic_feeds_cache.clear()
    server.thread.start()
    try:
        yield server
    finally:
        server.server.shutdown()
        server.server.server_close()
        server.thread.join()
        topic_feeds_cache.clear()


@pytest.mark.asyncio
async def test_real_browser_bootstrap_http_requests_pagination_and_cache(upstream: LocalDouyinUpstream) -> None:
    client = upstream.client()
    cookie = "sessionid_ss=account-a; custom_token=padding=="
    items = await fetch_topic_feeds_by_cache("示例话题", cookie, 45, client=client)
    assert [item.id for item in items] == [
        "douyin.aweme.3",
        "douyin.aweme.1",
        "douyin.aweme.2",
        "douyin.aweme.9",
        "douyin.aweme.4",
    ]
    authors = set()
    for item in items:
        assert item.author is not None
        authors.add(item.author.url)
    assert len(authors) == 5
    assert items[0].content_html is not None
    assert "<img" in items[0].content_html
    assert [request["query"]["offset"] for request in upstream.search_requests] == [["0"], ["15"], ["30"]]
    assert upstream.search_requests[1]["query"]["search_id"] == ["search-session"]
    for request in upstream.search_requests:
        headers = {key.lower(): value for key, value in request["headers"].items()}
        assert headers["x-tt-argus"] == "1"
        assert headers["uifid"] == "runtime-fingerprint"
        assert headers["user-agent"] == upstream.user_agents[0]
        assert "sessionid_ss=account-a" in headers["cookie"]
        assert "custom_token" not in parse_cookies(headers["cookie"])
        assert "Macintosh; Intel Mac OS X 10_15_7" in headers["user-agent"]
        assert request["query"]["os_name"] == ["Mac OS"]
        assert request["query"]["os_version"] == ["10.15.7"]
        assert request["query"]["msToken"] == ["runtime-token=="]
        assert request["query"]["keyword"] == ["#示例话题"]
        assert json.loads(request["query"]["filter_selected"][0]) == {"sort_type": "2", "publish_time": "0"}
    cached = await fetch_topic_feeds_by_cache("示例话题", cookie, 45, client=client)
    assert cached == items
    assert upstream.homepage_requests == 1
    await fetch_topic_feeds_by_cache("示例话题", "sessionid_ss=account-b", 45, client=client)
    assert upstream.homepage_requests == 2


@pytest.mark.asyncio
@pytest.mark.parametrize(
    ("cookie", "expected_bootstrap_cookie"),
    [
        (
            "sessionid_ss=account==; UIFID=stale-fingerprint; UIFID_TEMP=stale-temp; "
            "msToken=stale-token==; custom_token=padding==",
            "sessionid_ss=account==",
        ),
        ("sessionid_ss=account==", "sessionid_ss=account=="),
        ("sessionid=legacy==; custom_token=padding==", "sessionid=legacy==; custom_token=padding=="),
        ("sessionid_ss=; sessionid=legacy==", "sessionid_ss=; sessionid=legacy=="),
    ],
)
async def test_topic_bootstrap_login_cookie_and_runtime_fingerprint(
    upstream: LocalDouyinUpstream, cookie: str, expected_bootstrap_cookie: str
) -> None:
    posts = await upstream.client().fetch("示例话题", cookie, 2)
    assert len(posts) == 3
    bootstrap_headers = {key.lower(): value for key, value in upstream.homepage_headers[0].items()}
    assert parse_cookies(bootstrap_headers["cookie"]) == parse_cookies(expected_bootstrap_cookie)
    search_request = upstream.search_requests[0]
    search_headers = {key.lower(): value for key, value in search_request["headers"].items()}
    assert search_headers["user-agent"] == bootstrap_headers["user-agent"]
    assert "Macintosh; Intel Mac OS X 10_15_7" in search_headers["user-agent"]
    assert search_request["query"]["os_name"] == ["Mac OS"]
    assert search_request["query"]["os_version"] == ["10.15.7"]
    assert search_request["query"]["msToken"] == ["runtime-token=="]
    assert search_headers["uifid"] == "runtime-fingerprint"
    assert parse_cookies(search_headers["cookie"]) == {
        **parse_cookies(expected_bootstrap_cookie),
        "UIFID_TEMP": "runtime-fingerprint",
    }


@pytest.mark.asyncio
async def test_later_page_challenge_does_not_cache_partial_results(upstream: LocalDouyinUpstream) -> None:
    upstream.mode = "later_challenge"
    client = upstream.client()
    with pytest.raises(DouyinSearchError) as exc:
        await fetch_topic_feeds_by_cache("示例话题", "sessionid_ss=value", 45, client=client)
    assert exc.value.status_code == 503
    assert len(topic_feeds_cache) == 0
    upstream.mode = "posts"
    assert len(await fetch_topic_feeds_by_cache("示例话题", "sessionid_ss=value", 45, client=client)) == 5


@pytest.mark.asyncio
@pytest.mark.parametrize(
    ("mode", "status"),
    [
        ("challenge", 503),
        ("bootstrap_challenge", 503),
        ("empty_body", 502),
        ("logged_out", 401),
        ("stuck_cursor", 502),
        ("missing_search_id", 502),
    ],
)
async def test_restricted_or_invalid_responses_are_errors(
    upstream: LocalDouyinUpstream, mode: str, status: int
) -> None:
    upstream.mode = mode
    before = _playwright_capacity_limiter.in_use
    with pytest.raises(DouyinSearchError) as exc:
        await upstream.client().fetch("示例话题", "sessionid_ss=value", 45)
    assert exc.value.status_code == status
    assert _playwright_capacity_limiter.in_use == before


@pytest.mark.asyncio
async def test_verified_empty_results_and_post_limit(upstream: LocalDouyinUpstream) -> None:
    upstream.mode = "empty_feed"
    assert await upstream.client().fetch("示例话题", "sessionid_ss=value") == []
    upstream.mode = "posts"
    assert len(await fetch_topic_feeds("示例话题", "sessionid_ss=value", 2, client=upstream.client())) == 2
    assert len(upstream.search_requests) == 2


@pytest.mark.asyncio
@pytest.mark.parametrize(
    ("max_posts", "pages"), [(1, 1), (15, 1), (16, 2), (30, 2), (31, 3), (45, 3), (46, 4), (120, 8)]
)
async def test_page_budget_comes_from_max_posts_without_filling_short_results(
    upstream: LocalDouyinUpstream, max_posts: int, pages: int
) -> None:
    items = await fetch_topic_feeds("示例话题", "sessionid_ss=value", max_posts, client=upstream.client())
    assert 0 < len(items) <= max_posts
    assert [request["query"]["offset"] for request in upstream.search_requests] == [
        [str(index * 15)] for index in range(pages)
    ]
    assert all(request["query"]["count"] == ["15"] for request in upstream.search_requests)
    if max_posts > 1:
        assert "douyin.aweme.9" in {item.id for item in items}


@pytest.mark.asyncio
async def test_default_fetch_stays_on_first_page_and_ignores_later_challenge(upstream: LocalDouyinUpstream) -> None:
    upstream.mode = "later_challenge"
    items = await fetch_topic_feeds_by_cache("示例话题", "sessionid_ss=value", client=upstream.client())
    assert len(items) == 3
    assert len(upstream.search_requests) == 1
    assert len(topic_feeds_cache) == 1


@pytest.mark.asyncio
async def test_explicit_third_page_verification_still_fails_without_caching(upstream: LocalDouyinUpstream) -> None:
    upstream.mode = "third_page_challenge"
    client = upstream.client()
    assert len(await fetch_topic_feeds_by_cache("示例话题", "sessionid_ss=value", 30, client=client)) == 4
    before = len(topic_feeds_cache)
    with pytest.raises(DouyinSearchError) as exc:
        await fetch_topic_feeds_by_cache("示例话题", "sessionid_ss=value", 45, client=client)
    assert exc.value.status_code == 503
    assert len(topic_feeds_cache) == before


@pytest.mark.asyncio
async def test_upstream_end_stops_before_page_budget(upstream: LocalDouyinUpstream) -> None:
    upstream.mode = "early_end"
    assert len(await upstream.client().fetch("示例话题", "sessionid_ss=value", 120)) == 3
    assert len(upstream.search_requests) == 1


@pytest.mark.asyncio
async def test_timeout_releases_browser_slot(upstream: LocalDouyinUpstream) -> None:
    upstream.mode = "slow"
    before = _playwright_capacity_limiter.in_use
    with pytest.raises(TimeoutError):
        async with asyncio.timeout(0.5):
            await upstream.client().fetch("示例话题", "sessionid_ss=value")
    assert _playwright_capacity_limiter.in_use == before


@pytest.mark.asyncio
async def test_global_capacity_is_respected(upstream: LocalDouyinUpstream) -> None:
    leases = []
    try:
        for _ in range(_playwright_capacity_limiter.capacity - _playwright_capacity_limiter.in_use):
            leases.append(acquire_playwright_slot("douyin-capacity-test"))
        with pytest.raises(PlaywrightCapacityError):
            await upstream.client().fetch("示例话题", "sessionid_ss=value")
    finally:
        for lease in leases:
            lease.release()


@pytest.mark.parametrize("status", [403, 429, 500])
def test_upstream_http_failure_is_not_an_empty_feed(status: int) -> None:
    with pytest.raises(DouyinSearchError) as exc:
        search_payload(httpx.Response(status))
    assert exc.value.status_code == (503 if status in (403, 429) else 502)


def test_http_proxy_selection_and_bypass_match_browser() -> None:
    environment = {"HTTPS_PROXY": "http://proxy.example:7890", "NO_PROXY": "127.0.0.1,localhost"}
    assert httpx_proxy("http://127.0.0.1:8000", environment) is None
    https_proxy = httpx_proxy("https://www.douyin.com", environment)
    http_proxy = httpx_proxy("https://www.douyin.com", {"HTTP_PROXY": "http://proxy.example:7890"})
    assert https_proxy is not None
    assert http_proxy is not None
    assert str(https_proxy.url) == "http://proxy.example:7890"
    assert str(http_proxy.url) == "http://proxy.example:7890"
