import json
import logging
import re
from html import escape
from typing import Any, Awaitable, Callable, TypedDict, cast

import httpx
from bs4 import BeautifulSoup as Soup
from bs4 import Tag
from cachetools import FIFOCache, cached
from fastapi import FastAPI, Request
from starlette.middleware.base import BaseHTTPMiddleware
from starlette.responses import Response

from rssapi.applications.rss.schemas.rss.jsonfeed import JSONFeedItem
from rssapi.core.responses import PrettyJSONFeedResponse
from rssapi.core.settings import settings
from rssapi.utils.md import markdown_parse
from rssapi.utils.media_title import MEDIA_TITLE_RULES as DEFAULT_MEDIA_TITLE_RULES
from rssapi.utils.media_title import MediaTitleDetector

app = FastAPI()
logger = logging.getLogger(__file__)
JSON_FEED_VERSION_1 = "https://jsonfeed.org/version/1"


class JSONFeedResponseData(TypedDict):
    body: dict[str, Any]
    headers: dict[str, str]


def add_middleware(app: FastAPI):
    middlewares = [
        MarkdownRenderMiddleware,
        TelegramFeedFilterMiddleware,
        NGAFeedFilterMiddleware,
        NodeseekFeedFilterMiddleware,
        AddTwitterHTMLFeedMiddleware,
        UpdateTelegraphHTMLFeedMiddleware,
        FillFeedAuthorFromItemsMiddleware,
        FillFeedIconFromAuthorAvatarMiddleware,
        ExtractHashtagMiddleware,
        AddMediaTitlePrefixMiddleware,
        LimitTitleLengthMiddleware,
        AppendOriginalPostLinkMiddleware,
        ClearHomePageUrlMiddleware,
    ]
    for middleware in middlewares:
        app.add_middleware(middleware)


class BaseJSONFeedMiddleware(BaseHTTPMiddleware):
    def should_process(self, request: Request, response: Response) -> bool:
        content_type = response.headers.get("content-type")
        return bool(content_type and content_type.startswith("application/feed+json"))

    async def get_response_body_bytes(self, response: Response) -> bytes:
        body_iterator = getattr(response, "body_iterator", None)
        if body_iterator is not None:
            response_body = b""
            async for chunk in body_iterator:
                response_body += chunk
            return response_body
        return response.body

    async def get_jsonfeed_response(self, response: Response) -> JSONFeedResponseData:
        response_body = await self.get_response_body_bytes(response)
        body = json.loads(response_body)
        headers = dict(response.headers)
        headers.pop("content-length", None)
        return {"body": body, "headers": headers}

    def transform_body(self, body: dict[str, Any], request: Request) -> dict[str, Any]:
        return body

    async def dispatch(
        self, request: Request, call_next: Callable[[Request], Awaitable[Response]]
    ) -> Response | PrettyJSONFeedResponse:
        response = await call_next(request)
        if not self.should_process(request, response):
            return response

        response_data = await self.get_jsonfeed_response(response)
        body = self.transform_body(response_data["body"], request)
        return PrettyJSONFeedResponse(
            body,
            status_code=response.status_code,
            headers=response_data["headers"],
        )


class BaseJSONFeedItemsMiddleware(BaseJSONFeedMiddleware):
    def transform_item(self, payload: dict[str, Any]) -> dict[str, Any]:
        return payload

    def transform_items(self, items: list[dict[str, Any]]) -> list[dict[str, Any]]:
        return [self.transform_item(item) for item in items]

    def transform_body(self, body: dict[str, Any], request: Request) -> dict[str, Any]:
        if body.get("version") != JSON_FEED_VERSION_1:
            return body

        items = body.get("items")
        if isinstance(items, list):
            body["items"] = self.transform_items(items)
        return body


class BaseJSONFeedItemModelMiddleware(BaseJSONFeedItemsMiddleware):
    def transform_feed_item(self, feed: JSONFeedItem) -> JSONFeedItem:
        return feed

    def transform_item(self, payload: dict[str, Any]) -> dict[str, Any]:
        feed = JSONFeedItem.model_validate(payload)
        feed = self.transform_feed_item(feed)
        return feed.model_dump()


class AddTwitterHTMLFeedMiddleware(BaseJSONFeedItemModelMiddleware):
    @cached(FIFOCache(maxsize=1024))
    def make_html_by_url(self, url: str):
        output = []

        resp = httpx.get(url, verify=False)
        document = Soup(resp.text, "lxml")
        images = document.find_all("meta", property="og:image")

        for image in images:
            href = cast(Tag, image)["content"]

            ele = f"<img src='{href}'></img>"
            output.append(ele)
        return "\n".join(output)

    def transform_feed_item(self, feed: JSONFeedItem) -> JSONFeedItem:
        if feed.content_html:
            p = r"(https://fixupx.com/.*?/status/\d+)"
            result = re.search(p, feed.content_html)
            if result:
                contents = self.make_html_by_url(result.group(1))
                feed.content_html = f"{feed.content_html}<br>{contents}"
        return feed


class UpdateTelegraphHTMLFeedMiddleware(BaseJSONFeedItemModelMiddleware):
    @cached(FIFOCache(maxsize=1024))
    def make_html_by_url(self, url: str) -> str:
        res = httpx.get(url)
        doc = Soup(res.text, "lxml")
        return "<br/>".join([str(img) for img in doc.find_all("img")])

    def transform_feed_item(self, feed: JSONFeedItem) -> JSONFeedItem:
        if feed.content_html:
            document = Soup(feed.content_html, "lxml")
            for tag in document.find_all("a"):
                tag = cast(Tag, tag)
                href = (tag and tag.attrs and tag.attrs["href"]) or None
                if isinstance(href, str) and href.startswith("https://telegra.ph"):
                    extend_img_content = self.make_html_by_url(href)
                    feed.content_html = f"{feed.content_html}{extend_img_content}"
                    logger.debug(f"[UpdateTelegraphHTMLFeedMiddleware] Added img for {href}")
        return feed


class BaseFeedFilterMiddleware(BaseJSONFeedItemsMiddleware):
    BLOCK_TAG: list[str] = []
    BLOCK_CONTENT: list[str] = []

    BLOCK_REGEX_CONTENT: list[str] = []
    BLOCK_REGEX_TITLE: list[str] = []

    MATCH_URL_PATTERN = r""

    def should_process(self, request: Request, response: Response) -> bool:
        return super().should_process(request, response) and (
            re.match(self.__class__.MATCH_URL_PATTERN, request.url.path) is not None
        )

    def filter_by_block(self, item: dict[str, Any]) -> bool:
        tags = item.get("tags") or []
        for tag in self.__class__.BLOCK_TAG:
            if tag in tags:
                logger.debug(f"[{self.__class__.__name__}] skip by block tag matched: {tag}")
                return False

        for block in self.__class__.BLOCK_CONTENT:
            content_html = item.get("content_html")
            if content_html and block in content_html:
                logger.debug(f"[{self.__class__.__name__}] skip by block content matched: {block}")
                return False
            content_text = item.get("content_text")
            if content_text and block in content_text:
                logger.debug(f"[{self.__class__.__name__}] skip by block content matched: {block}")
                return False

        for pattern in self.__class__.BLOCK_REGEX_CONTENT:
            content_html = item.get("content_html")
            if content_html and re.search(pattern, content_html):
                logger.debug(f"[{self.__class__.__name__}] skip by regex content matched: {pattern}")
                return False
            content_text = item.get("content_text")
            if content_text and re.search(pattern, content_text):
                logger.debug(f"[{self.__class__.__name__}] skip by regex content matched: {pattern}")
                return False

        for pattern in self.__class__.BLOCK_REGEX_TITLE:
            title = item.get("title")
            if title and re.search(pattern, title):
                logger.debug(f"[{self.__class__.__name__}] skip by regex title matched: {pattern}")
                return False
        return True

    def transform_items(self, items: list[dict[str, Any]]) -> list[dict[str, Any]]:
        return [item for item in items if self.filter_by_block(item)]


class TelegramFeedFilterMiddleware(BaseFeedFilterMiddleware):
    BLOCK_TAG = ["#广告", "#互推", "#频道互推", "#群组互推"]
    BLOCK_CONTENT = [
        "TG必备的搜索引擎，极搜帮你精准找到，想要的群组、频道、音乐 、视频",
        "https://hongxingdl.com",
        "搜 蒸蒸日上 概率有5元猫卡",
        "<code>ikelee</code>",
        "AI 账号会员自助平台",
        "小信商店",
        "CardoPay",
        "SNKRX",
    ]

    MATCH_URL_PATTERN = r"/api/rss/telegram/"
    BLOCK_REGEX_TITLE = [r".*.*机场优惠活动.*.*"]


class NodeseekFeedFilterMiddleware(BaseFeedFilterMiddleware):
    BLOCK_REGEX_CONTENT = [r"(?i)HostDZire"]
    BLOCK_REGEX_TITLE = [r"(?i)HostDZire"]

    MATCH_URL_PATTERN = r"/api/rss/nodeseek/"


class NGAFeedFilterMiddleware(BaseFeedFilterMiddleware):
    BLOCK_REGEX_CONTENT = ["预制菜"]
    BLOCK_REGEX_TITLE = ["预制菜"]

    MATCH_URL_PATTERN = r"/api/rss/nga/"


class ExtractHashtagMiddleware(BaseJSONFeedItemModelMiddleware):
    """从 content_text 或 content_html 中提取 hashtag 并写入 tags 字段"""

    HASHTAG_PATTERN = re.compile(r"#(\w+)", re.UNICODE)

    def extract_hashtags(self, payload: dict[str, Any]) -> dict[str, Any]:
        return self.transform_item(payload)

    def transform_feed_item(self, feed: JSONFeedItem) -> JSONFeedItem:
        text = feed.content_text or feed.content_html
        if text:
            found = self.HASHTAG_PATTERN.findall(text)
            if found:
                existing = set(feed.tags or [])
                existing.update(f"#{tag}" for tag in found)
                feed.tags = sorted(existing)
        return feed


class AddMediaTitlePrefixMiddleware(BaseJSONFeedItemModelMiddleware):
    MEDIA_TITLE_RULES: dict[str, MediaTitleDetector] = DEFAULT_MEDIA_TITLE_RULES

    def transform_feed_item(self, feed: JSONFeedItem) -> JSONFeedItem:
        if not feed.content_html:
            return feed

        title = feed.title or ""
        document = Soup(feed.content_html, "lxml")

        for prefix, detector in self.MEDIA_TITLE_RULES.items():
            if prefix in title:
                continue

            if detector(document):
                title = f"{prefix} {title}" if title else prefix

        feed.title = title
        return feed


class LimitTitleLengthMiddleware(BaseJSONFeedItemModelMiddleware):
    def transform_feed_item(self, feed: JSONFeedItem) -> JSONFeedItem:
        max_title_length = settings.middleware.max_title_length
        if max_title_length > 0 and feed.title:
            feed.title = feed.title[:max_title_length]
        return feed


class AppendOriginalPostLinkMiddleware(BaseJSONFeedItemModelMiddleware):
    def transform_feed_item(self, feed: JSONFeedItem) -> JSONFeedItem:
        if not feed.content_html or not feed.url:
            return feed

        safe_url = escape(str(feed.url), quote=True)
        feed.content_html = f'{feed.content_html}<p><a href="{safe_url}">查看原贴</a></p>'
        return feed


class FillFeedIconFromAuthorAvatarMiddleware(BaseJSONFeedMiddleware):
    """当顶层 author.avatar 存在时，用 avatar 覆盖 icon/favicon"""

    def transform_body(self, body: dict[str, Any], request: Request) -> dict[str, Any]:
        author = body.get("author")
        avatar = author.get("avatar") if isinstance(author, dict) else None
        if avatar:
            body["icon"] = avatar
            body["favicon"] = avatar
        return body


class FillFeedAuthorFromItemsMiddleware(BaseJSONFeedMiddleware):
    """当 JSONFeed 顶层 author 不存在时，从 items 中取第一个有 author 的条目填充"""

    def transform_body(self, body: dict[str, Any], request: Request) -> dict[str, Any]:
        if body.get("version") == JSON_FEED_VERSION_1 and not body.get("author"):
            for item in body.get("items", []):
                if item.get("author"):
                    body["author"] = item["author"]
                    break
        return body


class ClearHomePageUrlMiddleware(BaseJSONFeedMiddleware):
    """将 feed 的 home_page_url 设置为空字符串"""

    def transform_body(self, body: dict[str, Any], _: Request) -> dict[str, Any]:
        body["home_page_url"] = ""
        return body


class MarkdownRenderMiddleware(BaseJSONFeedItemModelMiddleware):
    """尝试对 content_text 进行 markdown 渲染, 并写进 content_html"""

    def transform_feed_item(self, feed: JSONFeedItem) -> JSONFeedItem:
        if feed.content_text and not feed.content_html:
            try:
                feed.content_html = markdown_parse(feed.content_text)
                feed.content_text = None
            except Exception:
                pass
        return feed
