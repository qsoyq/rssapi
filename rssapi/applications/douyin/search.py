import asyncio
import contextlib
import json
import os
import urllib.request
from collections.abc import Mapping
from typing import Any, Callable, cast
from urllib.parse import urlsplit

import httpx
from playwright._impl._api_structures import SetCookieParam
from playwright.async_api import Browser, BrowserContext, async_playwright

from rssapi.applications.douyin.utils import (
    DOUYIN_BASE_URL,
    TOPIC_PAGE_SIZE,
    parse_cookies,
    playwright_cookies,
    post_matches_topic,
)
from rssapi.utils.playwright import _browser_user_agent
from rssapi.utils.playwright_capacity import acquire_playwright_slot_async
from rssapi.utils.playwright_proxy import (
    playwright_launch_options,
    playwright_proxy_from_environment,
)

SEARCH_PATH = "/aweme/v1/web/general/search/single/"
# urllib's cross-platform environment matcher is available at runtime but absent from typeshed.
_proxy_bypass_environment = cast(
    Callable[[str, dict[str, str]], bool], getattr(urllib.request, "proxy_bypass_environment")
)
_FINGERPRINT_SCRIPT = """() => ({
    browser_version: navigator.userAgent.match(/Chrome\\/([^ ]+)/)?.[1],
    browser_platform: navigator.platform,
    cpu_core_num: navigator.hardwareConcurrency,
    device_memory: navigator.deviceMemory || 8,
    screen_width: screen.width,
    screen_height: screen.height,
    msToken: localStorage.getItem('xmst'),
    webid: localStorage.getItem('web_id') || localStorage.getItem('user_unique_id') || '',
    os_name: navigator.userAgent.includes('Windows') ? 'Windows' :
        navigator.userAgent.includes('Macintosh') ? 'Mac OS' : 'Linux',
    os_version: navigator.userAgent.includes('Macintosh') ? '10.15.7' :
        navigator.userAgent.includes('Windows') ? '10' : ''
})"""


class DouyinSearchError(Exception):
    def __init__(self, message: str, status_code: int = 502) -> None:
        super().__init__(message)
        self.status_code = status_code


def search_payload(response: httpx.Response) -> dict[str, Any]:
    if response.status_code == 401:
        raise DouyinSearchError("抖音登录态已失效", 401)
    if response.status_code in (403, 429):
        raise DouyinSearchError("抖音搜索暂时受限", 503)
    if response.status_code != 200:
        raise DouyinSearchError("抖音搜索上游响应异常")
    try:
        payload = response.json()
    except ValueError:
        raise DouyinSearchError("抖音搜索返回空响应或非 JSON 内容") from None
    if not isinstance(payload, dict):
        raise DouyinSearchError("抖音搜索响应结构异常")
    message = str(payload.get("status_msg") or "")
    if payload.get("status_code") == 2483 or "未登录" in message or "请先登录" in message:
        raise DouyinSearchError("抖音登录态已失效", 401)
    if payload.get("status_code") != 0:
        raise DouyinSearchError("抖音搜索上游返回错误")
    nil_info = payload.get("search_nil_info") or {}
    if isinstance(nil_info, dict):
        reasons = (nil_info.get("search_nil_type"), nil_info.get("search_nil_item"))
        if "verify_check" in reasons:
            raise DouyinSearchError("抖音搜索需要验证，暂时无法获取作品", 503)
        if "unknown" in reasons:
            raise DouyinSearchError("抖音搜索未完成")
    if not isinstance(payload.get("data"), list):
        raise DouyinSearchError("抖音搜索响应缺少作品列表")
    return payload


def httpx_proxy(base_url: str, environment: Mapping[str, str]) -> httpx.Proxy | None:
    proxy = playwright_proxy_from_environment(environment)
    if proxy is None:
        return None
    host = urlsplit(base_url).hostname or ""
    if _proxy_bypass_environment(host, {"no": proxy.get("bypass") or ""}):
        return None
    username = proxy.get("username")
    auth = (username, proxy.get("password") or "") if username is not None else None
    return httpx.Proxy(proxy["server"], auth=auth)


class DouyinTopicClient:
    def __init__(
        self,
        base_url: str = DOUYIN_BASE_URL,
        *,
        startup_wait: float = 5,
        page_delay: float = 2,
        environment: Mapping[str, str] | None = None,
    ) -> None:
        self.base_url = base_url.rstrip("/")
        self.startup_wait = startup_wait
        self.page_delay = page_delay
        self.environment = os.environ if environment is None else environment

    async def fetch(self, topic: str, cookie: str, max_posts: int = TOPIC_PAGE_SIZE) -> list[dict[str, Any]]:
        browser: Browser | None = None
        context: BrowserContext | None = None
        async with async_playwright() as playwright:
            lease = await acquire_playwright_slot_async("DouyinTopic")
            try:
                browser = await playwright.chromium.launch(
                    **playwright_launch_options(headless=True, environment=self.environment)
                )
                # Linux UA/OS search parameters trigger verify_check for otherwise valid sessions.
                user_agent = _browser_user_agent(browser.version, runtime_platform="darwin")
                context = await browser.new_context(user_agent=user_agent, locale="zh-CN")
                # Imported browser fingerprints can challenge a fresh context; regenerate them here.
                sessionid_ss = parse_cookies(cookie).get("sessionid_ss")
                bootstrap_cookie = f"sessionid_ss={sessionid_ss}" if sessionid_ss else cookie
                auth_cookies: list[SetCookieParam] = [
                    {"name": entry["name"], "value": entry["value"], "url": entry["url"]}
                    for entry in playwright_cookies(bootstrap_cookie, self.base_url)
                ]
                await context.add_cookies(auth_cookies)
                page = await context.new_page()
                await page.goto(f"{self.base_url}/", wait_until="domcontentloaded", timeout=25000)
                await page.wait_for_timeout(self.startup_wait * 1000)
                if "验证码" in await page.title() or await page.locator("#captcha_container").is_visible():
                    raise DouyinSearchError("抖音会话初始化需要验证", 503)
                fingerprint = await page.evaluate(_FINGERPRINT_SCRIPT)
                runtime_cookies = {
                    entry["name"]: entry["value"] for entry in await context.cookies(self.base_url) if entry["name"]
                }
                uifid = runtime_cookies.get("UIFID") or runtime_cookies.get("UIFID_TEMP")
                if not uifid or not fingerprint.get("msToken"):
                    raise DouyinSearchError("抖音会话初始化未完成", 503)
                headers = {
                    "User-Agent": user_agent,
                    "Referer": page.url,
                    "Accept": "application/json",
                    "uifid": uifid,
                    "x-tt-argus": "1",
                }
                params = self._query(topic, fingerprint)
                async with httpx.AsyncClient(
                    headers=headers,
                    cookies=runtime_cookies,
                    proxy=httpx_proxy(self.base_url, self.environment),
                    trust_env=False,
                    timeout=25,
                    follow_redirects=True,
                ) as client:
                    return await self._pages(client, topic, params, max_posts)
            except httpx.TimeoutException:
                raise
            except httpx.RequestError:
                raise DouyinSearchError("抖音搜索请求失败") from None
            finally:
                try:
                    if context is not None:
                        with contextlib.suppress(Exception):
                            await context.close()
                finally:
                    try:
                        if browser is not None:
                            with contextlib.suppress(Exception):
                                await browser.close()
                    finally:
                        lease.release()

    @staticmethod
    def _query(topic: str, fingerprint: dict[str, Any]) -> dict[str, str]:
        params = {
            "device_platform": "webapp",
            "aid": "6383",
            "channel": "channel_pc_web",
            "version_code": "190600",
            "version_name": "19.6.0",
            "update_version_code": "170400",
            "pc_client_type": "1",
            "cookie_enabled": "true",
            "browser_language": "zh-CN",
            "browser_name": "Chrome",
            "browser_online": "true",
            "engine_name": "Blink",
            "engine_version": str(fingerprint["browser_version"]),
            "platform": "PC",
            "effective_type": "4g",
            "round_trip_time": "50",
            "search_channel": "aweme_general",
            "enable_history": "1",
            "keyword": f"#{topic}",
            "search_source": "tab_search",
            "query_correct_type": "1",
            "is_filter_search": "1",
            "count": str(TOPIC_PAGE_SIZE),
            "need_filter_settings": "1",
            "list_type": "multi",
            "filter_selected": json.dumps({"sort_type": "2", "publish_time": "0"}, separators=(",", ":")),
        }
        params.update({key: str(value) for key, value in fingerprint.items() if value is not None and value != ""})
        return params

    async def _pages(
        self, client: httpx.AsyncClient, topic: str, params: dict[str, str], max_posts: int
    ) -> list[dict[str, Any]]:
        posts: dict[str, dict[str, Any]] = {}
        offset = 0
        search_id = ""
        visited = {offset}
        page_budget = (max_posts + TOPIC_PAGE_SIZE - 1) // TOPIC_PAGE_SIZE
        for page_number in range(page_budget):
            response = await client.get(
                f"{self.base_url}{SEARCH_PATH}", params={**params, "offset": str(offset), "search_id": search_id}
            )
            payload = search_payload(response)
            for entry in payload["data"]:
                post = entry.get("aweme_info") if isinstance(entry, dict) else None
                if isinstance(post, dict) and post.get("aweme_id") and post_matches_topic(topic, post):
                    posts.setdefault(str(post["aweme_id"]), post)
            if len(posts) >= max_posts or not payload.get("has_more") or page_number + 1 == page_budget:
                break
            try:
                offset = int(payload["cursor"])
            except (KeyError, ValueError, TypeError):
                raise DouyinSearchError("抖音搜索分页游标异常") from None
            if offset in visited:
                raise DouyinSearchError("抖音搜索分页游标未推进")
            visited.add(offset)
            log_pb = payload.get("log_pb") or {}
            next_search_id = payload.get("search_id") or (log_pb.get("impr_id") if isinstance(log_pb, dict) else None)
            if not isinstance(next_search_id, str) or not next_search_id:
                raise DouyinSearchError("抖音搜索分页缺少搜索 ID")
            search_id = next_search_id
            await asyncio.sleep(self.page_delay)
        return list(posts.values())
