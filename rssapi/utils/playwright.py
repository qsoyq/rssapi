import asyncio
import json
import logging
import time
from abc import ABC

from playwright import async_api
from playwright._impl._errors import TargetClosedError

logger = logging.getLogger(__file__)


class AsyncPlaywright(ABC):
    WATCH_URL_PATH = ""
    HEADLESS = True
    MAX_RETRIES = 3
    RETRY_DELAY = 2

    def __init__(
        self,
        url: str,
        user_agent: str = "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/140.0.0.0 Safari/537.36",
    ):
        self.url = url
        self._cookies: list = []
        self.user_agent = user_agent
        self._start_ts = time.time()
        self.fut: asyncio.Future[str | dict] = asyncio.Future()

    def add_cookies(self, cookies: list):
        self._cookies.extend(cookies)

    def cookies_by_str(self, cookie: str, url: str) -> list:
        _cookies = [x.strip().split("=") for x in cookie.split(";") if x != ""]
        _cookies_dict = dict([x for x in _cookies if len(x) == 2])
        cookies = [{"name": k, "value": v, "url": url} for k, v in _cookies_dict.items()]
        return cookies

    async def run(self):
        logger.debug(f"{self.__class__.__name__} run {self.url}")
        url = self.url
        cookies = self._cookies
        last_exc: Exception | None = None

        for attempt in range(1, self.MAX_RETRIES + 1):
            if attempt > 1:
                self.fut = asyncio.Future()
                delay = self.RETRY_DELAY * attempt
                logger.info(f"{self.__class__.__name__} retry {attempt}/{self.MAX_RETRIES} after {delay}s: {self.url}")
                await asyncio.sleep(delay)

            async with async_api.async_playwright() as playwright:
                logger.debug(f"{self.__class__.__name__} enter playwright context: {self.url}")
                chromium = playwright.chromium
                browser = await chromium.launch(headless=self.__class__.HEADLESS)
                logger.debug(f"{self.__class__.__name__} new browser: {self.url}")
                context = await browser.new_context(user_agent=self.user_agent)
                logger.debug(f"{self.__class__.__name__} new context: {self.url}")
                if cookies:
                    await context.add_cookies(cookies)  # type: ignore

                page = await context.new_page()
                logger.debug(f"{self.__class__.__name__} new page: {self.url}")
                page.on("response", self.on_response)

                try:
                    logger.debug(f"{self.__class__.__name__} goto page: {self.url}")
                    await page.goto(url)
                    logger.debug(f"{self.__class__.__name__} wait for: {self.url}")
                    result = await self.fut
                    logger.debug(f"{self.__class__.__name__} fetch result done, {self.url}")
                    return result
                except Exception as e:
                    last_exc = e
                    if self._is_retryable(e) and attempt < self.MAX_RETRIES:
                        logger.warning(f"{self.__class__.__name__} [run] 可重试错误 (attempt {attempt}): {e}")
                        continue
                    logger.warning(f"{self.__class__.__name__} [run] 运行错误, 请检查用户 id: {self.url}")
                    raise e
                finally:
                    await context.close()
                    await browser.close()
                    logger.debug(f"{self.__class__.__name__} close browser: {self.url}")

        raise last_exc  # type: ignore[misc]

    @staticmethod
    def _is_retryable(exc: Exception) -> bool:
        retryable_patterns = (
            "ERR_CONNECTION_RESET",
            "ERR_CONNECTION_REFUSED",
            "ERR_CONNECTION_TIMED_OUT",
            "ERR_NETWORK_CHANGED",
            "ERR_INTERNET_DISCONNECTED",
            "ERR_NAME_NOT_RESOLVED",
        )
        msg = str(exc)
        return any(p in msg for p in retryable_patterns)

    async def on_response(self, response: async_api.Response):
        try:
            assert self.__class__.WATCH_URL_PATH, "未指定需要监控的请求路径"
            if self.__class__.WATCH_URL_PATH in response.url:
                try:
                    logger.debug(f"{self.__class__.__name__} [on_response] {self.url} {response.request.method}")
                    is_json = "application/json" in response.headers.get("content-type", "")
                    text = await response.text()
                    body = text
                    try:
                        if is_json:
                            body = json.loads(text)
                    except json.decoder.JSONDecodeError as e:
                        logger.warning(f"[playwright][on_response] decode json error: {self.url}\t{e}")
                    if self.fut and not self.fut.done():
                        self.fut.set_result(body)
                except Exception as e:
                    if self.fut and not self.fut.done():
                        self.fut.set_exception(e)
        except TargetClosedError as e:
            logger.warning(f"{self.__class__.__name__} on_response: TargetClosedError {e}")
