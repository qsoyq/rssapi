import asyncio
import hashlib
import re
import sys
from dataclasses import dataclass
from pathlib import Path
from typing import Any, cast
from urllib.parse import unquote, urlsplit

from cachetools import TTLCache
from playwright.async_api import Browser, BrowserContext
from playwright.async_api import Error as PlaywrightError
from playwright.async_api import Page, ProxySettings, Response
from playwright.async_api import TimeoutError as PlaywrightTimeoutError
from playwright.async_api import async_playwright

from rssapi.applications.tiktok.utils import TIKTOK_BASE_URL, normalize_username
from rssapi.core.settings import settings
from rssapi.utils.cache import RandomTTLCache

_PublicCacheKey = tuple[str, int, str, float, str | None]
_InflightKey = tuple[_PublicCacheKey, str | None, str | None]
_max_inflight = max(settings.tiktok.playwright_max_inflight, settings.tiktok.playwright_concurrency)

_COOKIE_NAME_RE = re.compile(r"^[!#$%&'*+\-.^_`|~0-9A-Za-z]+$")
_PROFILE_API_PATH = "/api/user/detail/"
_POST_API_PATHS = ("/api/post/item_list/", "/api/creator/item_list/")

_CHALLENGE_MARKERS = (
    "drag the slider to fit the puzzle",
    "complete the puzzle to continue",
    "security verification",
)
_NOT_FOUND_MARKERS = (
    "couldn't find this account",
    "couldn’t find this account",
    "account not found",
)
_PRIVATE_MARKERS = (
    "this account is private",
    "follow this account to see their videos",
)


class TikTokBrowserError(RuntimeError):
    def __init__(self, message: str, *, kind: str, status_code: int) -> None:
        super().__init__(message)
        self.kind = kind
        self.status_code = status_code


@dataclass(frozen=True)
class _FailureRecord:
    message: str
    kind: str
    status_code: int

    def to_exception(self) -> TikTokBrowserError:
        return TikTokBrowserError(self.message, kind=self.kind, status_code=self.status_code)


@dataclass
class _RuntimeState:
    browser_semaphore: asyncio.Semaphore
    result_cache: RandomTTLCache
    inflight_lock: asyncio.Lock
    inflight: dict[_InflightKey, asyncio.Task[tuple[dict[str, Any], list[dict[str, Any]]]]]
    failure_cache: TTLCache[_InflightKey, _FailureRecord]


_RUNTIME_STATE_ATTRIBUTE = "_rssapi_tiktok_runtime_state"


def _runtime_state() -> _RuntimeState:
    loop = asyncio.get_running_loop()
    state = getattr(loop, _RUNTIME_STATE_ATTRIBUTE, None)
    if isinstance(state, _RuntimeState):
        return state
    state = _RuntimeState(
        browser_semaphore=asyncio.Semaphore(settings.tiktok.playwright_concurrency),
        result_cache=RandomTTLCache(
            settings.tiktok.user_posts_cache_maxsize,
            settings.tiktok.user_posts_cache_ttl,
        ),
        inflight_lock=asyncio.Lock(),
        inflight={},
        failure_cache=TTLCache(
            maxsize=settings.tiktok.user_posts_cache_maxsize,
            ttl=60,
        ),
    )
    setattr(loop, _RUNTIME_STATE_ATTRIBUTE, state)
    return state


@dataclass(frozen=True)
class _CapturedPayload:
    kind: str
    payload: dict[str, Any]


def _find_profile_user(value: Any, username: str) -> dict[str, Any] | None:
    if isinstance(value, dict):
        unique_id = value.get("uniqueId")
        sec_uid = value.get("secUid")
        if isinstance(unique_id, str) and unique_id.lower() == username and isinstance(sec_uid, str) and sec_uid:
            return value
        for child in value.values():
            if user := _find_profile_user(child, username):
                return user
    elif isinstance(value, list):
        for child in value:
            if user := _find_profile_user(child, username):
                return user
    return None


def _validated_public_user(user: dict[str, Any], username: str) -> dict[str, Any]:
    private_account = user.get("privateAccount")
    secret = user.get("secret")
    if not isinstance(private_account, bool) or not isinstance(secret, bool):
        raise TikTokBrowserError(
            f"TikTok user privacy state is missing for @{username}",
            kind="invalid_payload",
            status_code=502,
        )
    if private_account or secret:
        raise TikTokBrowserError(
            f"TikTok profile is private: {username}",
            kind="private",
            status_code=403,
        )
    return user


def _payload_status(payload: dict[str, Any]) -> int | None:
    value = payload.get("statusCode", payload.get("status_code"))
    return value if isinstance(value, int) else None


def _payload_items(payload: dict[str, Any], username: str) -> list[dict[str, Any]] | None:
    raw_items = payload.get("itemList", payload.get("item_list"))
    if not isinstance(raw_items, list):
        return None
    items = [item for item in raw_items if isinstance(item, dict)]
    if not items:
        return []
    matching_items: list[dict[str, Any]] = []
    for item in items:
        author = item.get("author")
        if not isinstance(author, dict):
            continue
        unique_id = author.get("uniqueId")
        if isinstance(unique_id, str) and unique_id.lower() == username:
            matching_items.append(item)
    return matching_items or None


def _payload_has_more(payload: dict[str, Any]) -> bool:
    return bool(payload.get("hasMore") or payload.get("hasMorePrevious") or payload.get("has_more"))


def _browser_user_agent(browser_version: str) -> str:
    platform = "Macintosh; Intel Mac OS X 10_15_7" if sys.platform == "darwin" else "X11; Linux x86_64"
    major_version = browser_version.split(".", 1)[0]
    return (
        f"Mozilla/5.0 ({platform}) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/{major_version}.0.0.0 Safari/537.36"
    )


def _playwright_proxy(proxy_url: str | None) -> ProxySettings | None:
    if proxy_url is None:
        return None
    parsed = urlsplit(proxy_url)
    if not parsed.scheme or not parsed.hostname:
        raise TikTokBrowserError(
            "TikTok Playwright proxy configuration is invalid",
            kind="configuration",
            status_code=503,
        )
    host = f"[{parsed.hostname}]" if ":" in parsed.hostname else parsed.hostname
    server = f"{parsed.scheme}://{host}"
    try:
        port = parsed.port
    except ValueError as exc:
        raise TikTokBrowserError(
            "TikTok Playwright proxy configuration is invalid",
            kind="configuration",
            status_code=503,
        ) from exc
    if port is not None:
        server = f"{server}:{port}"
    proxy: ProxySettings = {"server": server}
    if parsed.username is not None:
        proxy["username"] = unquote(parsed.username)
    if parsed.password is not None:
        proxy["password"] = unquote(parsed.password)
    return proxy


def _cookie_fingerprint(cookie_header: str | None) -> str | None:
    if cookie_header is None:
        return None
    return hashlib.sha256(cookie_header.encode()).hexdigest()


def _cookies_from_header(cookie_header: str, base_url: str) -> list[dict[str, Any]]:
    parsed_url = urlsplit(base_url)
    if parsed_url.hostname is None:
        raise TikTokBrowserError(
            "TikTok cookie target is invalid",
            kind="configuration",
            status_code=503,
        )
    domain = ".tiktok.com" if parsed_url.hostname.endswith("tiktok.com") else parsed_url.hostname
    cookies: list[dict[str, Any]] = []
    for pair in cookie_header.split(";"):
        name, separator, value = pair.strip().partition("=")
        if not separator or not name or not _COOKIE_NAME_RE.fullmatch(name):
            raise TikTokBrowserError(
                "TikTok Cookie header is invalid",
                kind="invalid_cookie",
                status_code=422,
            )
        cookies.append(
            {
                "name": name,
                "value": value,
                "domain": domain,
                "path": "/",
                "secure": parsed_url.scheme == "https",
                "sameSite": "Lax",
            }
        )
    if not cookies:
        raise TikTokBrowserError(
            "TikTok Cookie header is empty",
            kind="invalid_cookie",
            status_code=422,
        )
    return cookies


class TikTokPlaywright:
    def __init__(
        self,
        username: str,
        max_posts: int,
        *,
        base_url: str = TIKTOK_BASE_URL,
        timeout: float | None = None,
        proxy: str | None = None,
        storage_state_path: str | None = None,
        cookie_header: str | None = None,
    ) -> None:
        self.username = normalize_username(username)
        self.max_posts = max_posts
        self.base_url = base_url.rstrip("/")
        self.timeout = timeout or settings.tiktok.playwright_timeout
        self.proxy = proxy if proxy is not None else settings.tiktok.proxy
        self.cookie_header = cookie_header
        if cookie_header is not None:
            self.storage_state_path = None
        elif storage_state_path is not None:
            self.storage_state_path = storage_state_path
        else:
            self.storage_state_path = settings.tiktok.playwright_storage_state_path
        self._origin_host = urlsplit(self.base_url).hostname
        self._events: asyncio.Queue[_CapturedPayload] = asyncio.Queue()
        self._response_tasks: set[asyncio.Task[None]] = set()
        self._saw_malformed_posts = False

    async def run(self) -> tuple[dict[str, Any], list[dict[str, Any]]]:
        try:
            return await asyncio.wait_for(self._run_with_browser_slot(), timeout=self.timeout)
        except asyncio.TimeoutError as exc:
            raise TikTokBrowserError(
                f"TikTok browser timed out for @{self.username}",
                kind="timeout",
                status_code=504,
            ) from exc

    async def _run_with_browser_slot(self) -> tuple[dict[str, Any], list[dict[str, Any]]]:
        async with _runtime_state().browser_semaphore:
            return await self._run_browser()

    async def _run_browser(self) -> tuple[dict[str, Any], list[dict[str, Any]]]:
        browser_started = False
        try:
            async with async_playwright() as playwright:
                browser: Browser | None = None
                context: BrowserContext | None = None
                page: Page | None = None
                try:
                    browser = await playwright.chromium.launch(
                        channel="chromium",
                        headless=True,
                        proxy=_playwright_proxy(self.proxy),
                    )
                    browser_started = True
                    context_options: dict[str, Any] = {
                        "locale": "en-US",
                        "user_agent": _browser_user_agent(browser.version),
                        "viewport": {"width": 1440, "height": 1080},
                    }
                    if self.storage_state_path:
                        state_path = Path(self.storage_state_path)
                        if not state_path.is_file():
                            raise TikTokBrowserError(
                                "TikTok Playwright storage state file does not exist",
                                kind="configuration",
                                status_code=503,
                            )
                        context_options["storage_state"] = str(state_path)
                    context = await browser.new_context(**context_options)
                    if self.cookie_header is not None:
                        await context.add_cookies(cast(Any, _cookies_from_header(self.cookie_header, self.base_url)))
                    page = await context.new_page()
                    page.on("response", self._on_response)
                    await page.goto(
                        f"{self.base_url}/@{self.username}",
                        wait_until="domcontentloaded",
                        timeout=self.timeout * 1000,
                    )
                    return await self._collect(page)
                finally:
                    if page is not None:
                        page.remove_listener("response", self._on_response)
                    try:
                        await asyncio.wait_for(self._cleanup_browser(context, browser), timeout=3)
                    except (asyncio.TimeoutError, PlaywrightError):
                        pass
        except TikTokBrowserError:
            raise
        except PlaywrightTimeoutError as exc:
            raise TikTokBrowserError(
                f"TikTok browser navigation timed out for @{self.username}",
                kind="timeout",
                status_code=504,
            ) from exc
        except PlaywrightError as exc:
            kind = "browser_unavailable" if not browser_started else "browser_failure"
            raise TikTokBrowserError(
                f"TikTok browser failed for @{self.username}",
                kind=kind,
                status_code=503,
            ) from exc

    async def _cleanup_browser(self, context: BrowserContext | None, browser: Browser | None) -> None:
        response_tasks = tuple(self._response_tasks)
        for task in response_tasks:
            task.cancel()
        if response_tasks:
            await asyncio.gather(*response_tasks, return_exceptions=True)
        if context is not None:
            try:
                await context.close()
            except PlaywrightError:
                pass
        if browser is not None:
            try:
                await browser.close()
            except PlaywrightError:
                pass

    def _on_response(self, response: Response) -> None:
        task = asyncio.create_task(self._capture_response(response))
        self._response_tasks.add(task)
        task.add_done_callback(self._response_tasks.discard)

    async def _capture_response(self, response: Response) -> None:
        parsed_url = urlsplit(response.url)
        if parsed_url.hostname != self._origin_host or response.request.method != "GET" or response.status != 200:
            return
        content_type = response.headers.get("content-type", "").lower()
        if "json" not in content_type:
            return
        path = parsed_url.path.lower()
        is_profile_response = path == _PROFILE_API_PATH
        is_post_response = path in _POST_API_PATHS
        if not is_profile_response and not is_post_response:
            return
        try:
            payload = await response.json()
        except (PlaywrightError, ValueError):
            if is_post_response:
                self._saw_malformed_posts = True
            return
        if not isinstance(payload, dict):
            if is_post_response:
                self._saw_malformed_posts = True
            return
        kind = "profile" if is_profile_response else "posts"
        await self._events.put(_CapturedPayload(kind=kind, payload=payload))

    async def _collect(self, page: Page) -> tuple[dict[str, Any], list[dict[str, Any]]]:
        profile_user: dict[str, Any] | None = None
        posts: list[dict[str, Any]] = []
        seen_ids: set[str] = set()
        terminal_posts_seen = False

        while True:
            try:
                event = await asyncio.wait_for(self._events.get(), timeout=1.5)
            except TimeoutError:
                await self._raise_for_page_state(page)
                await page.mouse.wheel(0, 1200)
                continue

            status = _payload_status(event.payload)
            if status not in (None, 0):
                raise TikTokBrowserError(
                    f"TikTok returned status {status} for @{self.username}",
                    kind="upstream",
                    status_code=502,
                )

            if event.kind == "profile":
                candidate_user = _find_profile_user(event.payload, self.username)
                if candidate_user is not None:
                    profile_user = _validated_public_user(candidate_user, self.username)
                if profile_user is not None and terminal_posts_seen:
                    return profile_user, posts[: self.max_posts]
                continue

            items = _payload_items(event.payload, self.username)
            if items is None:
                self._saw_malformed_posts = True
                continue
            for item in items:
                item_id = str(item.get("id") or "")
                if not item_id or item_id in seen_ids:
                    continue
                author = item.get("author")
                if not isinstance(author, dict):
                    raise TikTokBrowserError(
                        f"TikTok post author is missing for @{self.username}",
                        kind="invalid_payload",
                        status_code=502,
                    )
                validated_author = _validated_public_user(author, self.username)
                seen_ids.add(item_id)
                posts.append(item)
                if profile_user is None:
                    profile_user = validated_author
                if len(posts) >= self.max_posts:
                    break

            terminal_posts_seen = not _payload_has_more(event.payload)
            if profile_user is not None and (len(posts) >= self.max_posts or terminal_posts_seen):
                return profile_user, posts[: self.max_posts]

            await page.mouse.wheel(0, 1200)

    async def _raise_for_page_state(self, page: Page) -> None:
        body_text = (await page.locator("body").inner_text(timeout=2000)).lower()
        if any(marker in body_text for marker in _CHALLENGE_MARKERS):
            raise TikTokBrowserError(
                f"TikTok requested browser verification for @{self.username}",
                kind="challenge",
                status_code=503,
            )
        if any(marker in body_text for marker in _NOT_FOUND_MARKERS):
            raise TikTokBrowserError(
                f"TikTok user not found: {self.username}",
                kind="not_found",
                status_code=404,
            )
        if any(marker in body_text for marker in _PRIVATE_MARKERS):
            raise TikTokBrowserError(
                f"TikTok profile is private: {self.username}",
                kind="private",
                status_code=403,
            )
        if self._saw_malformed_posts:
            raise TikTokBrowserError(
                f"TikTok returned invalid post data for @{self.username}",
                kind="invalid_payload",
                status_code=502,
            )


async def fetch_user_posts_v2(
    username: str,
    max_posts: int,
    *,
    base_url: str | None = None,
    timeout: float | None = None,
    proxy: str | None = None,
    storage_state_path: str | None = None,
    cookie_header: str | None = None,
) -> tuple[dict[str, Any], list[dict[str, Any]]]:
    scraper = TikTokPlaywright(
        username,
        max_posts,
        base_url=base_url or TIKTOK_BASE_URL,
        timeout=timeout,
        proxy=proxy,
        storage_state_path=storage_state_path,
        cookie_header=cookie_header,
    )
    return await scraper.run()


async def _fetch_and_cache(
    state: _RuntimeState,
    public_key: _PublicCacheKey,
    inflight_key: _InflightKey,
    *,
    cookie_header: str | None,
    storage_state_path: str | None,
) -> tuple[dict[str, Any], list[dict[str, Any]]]:
    try:
        try:
            return cast(tuple[dict[str, Any], list[dict[str, Any]]], state.result_cache[public_key])
        except KeyError:
            pass
        username, max_posts, base_url, timeout, proxy = public_key
        result = await fetch_user_posts_v2(
            username,
            max_posts,
            base_url=base_url,
            timeout=timeout,
            proxy=proxy,
            storage_state_path=storage_state_path,
            cookie_header=cookie_header,
        )
        state.result_cache[public_key] = result
        return result
    except TikTokBrowserError as exc:
        if exc.status_code in (429, 502, 503, 504):
            state.failure_cache[inflight_key] = _FailureRecord(
                message=str(exc),
                kind=exc.kind,
                status_code=exc.status_code,
            )
        raise
    finally:
        current_task = asyncio.current_task()
        async with state.inflight_lock:
            if state.inflight.get(inflight_key) is current_task:
                del state.inflight[inflight_key]


async def fetch_user_posts_v2_by_cache(
    username: str,
    max_posts: int,
    *,
    base_url: str | None = None,
    timeout: float | None = None,
    proxy: str | None = None,
    storage_state_path: str | None = None,
    cookie_header: str | None = None,
) -> tuple[dict[str, Any], list[dict[str, Any]]]:
    state = _runtime_state()
    resolved_proxy = proxy if proxy is not None else settings.tiktok.proxy
    if cookie_header is not None:
        resolved_storage_state_path = None
    elif storage_state_path is not None:
        resolved_storage_state_path = storage_state_path
    else:
        resolved_storage_state_path = settings.tiktok.playwright_storage_state_path
    public_key: _PublicCacheKey = (
        normalize_username(username),
        max_posts,
        (base_url or TIKTOK_BASE_URL).rstrip("/"),
        timeout or settings.tiktok.playwright_timeout,
        resolved_proxy,
    )
    inflight_key: _InflightKey = (
        public_key,
        _cookie_fingerprint(cookie_header),
        resolved_storage_state_path,
    )
    try:
        return cast(tuple[dict[str, Any], list[dict[str, Any]]], state.result_cache[public_key])
    except KeyError:
        pass

    async with state.inflight_lock:
        try:
            return cast(tuple[dict[str, Any], list[dict[str, Any]]], state.result_cache[public_key])
        except KeyError:
            failure = state.failure_cache.get(inflight_key)
            if failure is not None:
                raise failure.to_exception()
            task = state.inflight.get(inflight_key)
            if task is None:
                if len(state.inflight) >= _max_inflight:
                    raise TikTokBrowserError(
                        "TikTok browser queue is full",
                        kind="busy",
                        status_code=503,
                    )
                task = asyncio.create_task(
                    _fetch_and_cache(
                        state,
                        public_key,
                        inflight_key,
                        cookie_header=cookie_header,
                        storage_state_path=resolved_storage_state_path,
                    )
                )
                state.inflight[inflight_key] = task

    return await asyncio.shield(task)


async def clear_v2_cache() -> None:
    state = _runtime_state()
    async with state.inflight_lock:
        state.result_cache.clear()
        state.failure_cache.clear()


async def v2_inflight_count() -> int:
    state = _runtime_state()
    async with state.inflight_lock:
        return len(state.inflight)
