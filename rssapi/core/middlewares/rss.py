import json
import logging
import re
from typing import Awaitable, Callable, cast

import httpx
from bs4 import BeautifulSoup as Soup
from bs4 import Tag
from cachetools import FIFOCache, cached
from fastapi import FastAPI, Request
from starlette.middleware.base import BaseHTTPMiddleware
from starlette.responses import Response

from rssapi.applications.rss.schemas.rss.jsonfeed import JSONFeedItem
from rssapi.core.responses import PrettyJSONFeedResponse
from rssapi.utils.md import markdown_parse

app = FastAPI()
logger = logging.getLogger(__file__)


def add_middleware(app: FastAPI):
    middlewares = [
        MarkdownRenderMiddleware,
        TelegramFeedFilterMiddleware,
        NGAFeedFilterMiddleware,
        NodeseekFeedFilterMiddleware,
        AddTwitterHTMLFeedMiddleware,
        UpdateTelegraphHTMLFeedMiddleware,
        FillFeedAuthorFromItemsMiddleware,
        FillImageFromAuthorAvatarMiddleware,
        FillFeedIconFromAuthorAvatarMiddleware,
        ExtractHashtagMiddleware,
    ]
    for middleware in middlewares:
        app.add_middleware(middleware)


class AddTwitterHTMLFeedMiddleware(BaseHTTPMiddleware):
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

    def fixupx_match(self, item: dict):
        feed = JSONFeedItem(**item)

        if feed.content_html:
            p = r"(https://fixupx.com/.*?/status/\d+)"
            result = re.search(p, feed.content_html)
            if result:
                contents = self.make_html_by_url(result.group(1))
                feed.content_html = f"{feed.content_html}<br>{contents}"

        return feed.model_dump()

    async def dispatch(
        self, request: Request, call_next: Callable[[Request], Awaitable[Response]]
    ) -> Response | PrettyJSONFeedResponse:
        response = await call_next(request)
        path = request.url.path
        ct = response.headers.get("content-type")
        if ct and ct.startswith("application/feed+json") and path.startswith("/api/rss/"):
            response_body = b""
            async for chunk in response.body_iterator:  # type: ignore
                response_body += chunk
            body = json.loads(response_body)
            headers = dict(response.headers)
            headers.pop("content-length", None)
            if body.get("version") == "https://jsonfeed.org/version/1":
                body["items"] = list(map(self.fixupx_match, body["items"]))
            return PrettyJSONFeedResponse(body, status_code=response.status_code, headers=headers)
        return response


class UpdateTelegraphHTMLFeedMiddleware(BaseHTTPMiddleware):
    @cached(FIFOCache(maxsize=1024))
    def make_html_by_url(self, url: str) -> str:
        res = httpx.get(url)
        doc = Soup(res.text, "lxml")
        return "<br/>".join([str(img) for img in doc.find_all("img")])

    def fixupx_match(self, item: dict):
        feed = JSONFeedItem(**item)

        if feed.content_html:
            document = Soup(feed.content_html, "lxml")
            for tag in document.find_all("a"):
                tag = cast(Tag, tag)
                href = (tag and tag.attrs and tag.attrs["href"]) or None
                if isinstance(href, str) and href.startswith("https://telegra.ph"):
                    extend_img_content = self.make_html_by_url(href)
                    feed.content_html = f"{feed.content_html}{extend_img_content}"
                    logger.debug(f"[UpdateTelegraphHTMLFeedMiddleware] Added img for {href}")
        return feed.model_dump()

    async def dispatch(
        self, request: Request, call_next: Callable[[Request], Awaitable[Response]]
    ) -> Response | PrettyJSONFeedResponse:
        response = await call_next(request)
        path = request.url.path
        ct = response.headers.get("content-type")
        if ct and ct.startswith("application/feed+json") and path.startswith("/api/rss/"):
            response_body = b""
            async for chunk in response.body_iterator:  # type: ignore
                response_body += chunk
            body = json.loads(response_body)
            headers = dict(response.headers)
            headers.pop("content-length", None)
            if body.get("version") == "https://jsonfeed.org/version/1":
                body["items"] = list(map(self.fixupx_match, body["items"]))
            return PrettyJSONFeedResponse(body, status_code=response.status_code, headers=headers)
        return response


class BaseFeedFilterMiddleware(BaseHTTPMiddleware):
    BLOCK_TAG: list[str] = []
    BLOCK_CONTENT: list[str] = []

    BLOCK_REGEX_CONTENT: list[str] = []
    BLOCK_REGEX_TITLE: list[str] = []

    MATCH_URL_PATTERN = r""

    def filter_by_block(self, item: dict):
        tags = item["tags"] or []
        for tag in self.__class__.BLOCK_TAG:
            if tag in tags:
                logger.debug(f"[{self.__class__.__name__}] skip by block tag matched: {tag}")
                return False

        for block in self.__class__.BLOCK_CONTENT:
            if item["content_html"] and block in item["content_html"]:
                logger.debug(f"[{self.__class__.__name__}] skip by block content matched: {block}")
                return False
            if item["content_text"] and block in item["content_text"]:
                logger.debug(f"[{self.__class__.__name__}] skip by block content matched: {block}")
                return False

        for pattern in self.__class__.BLOCK_REGEX_CONTENT:
            if item["content_html"] and re.search(pattern, item["content_html"]):
                logger.debug(f"[{self.__class__.__name__}] skip by regex content matched: {pattern}")
                return False
            if item["content_text"] and re.search(pattern, item["content_text"]):
                logger.debug(f"[{self.__class__.__name__}] skip by regex content matched: {pattern}")
                return False

        for pattern in self.__class__.BLOCK_REGEX_TITLE:
            if item["title"] and re.search(pattern, item["title"]):
                logger.debug(f"[{self.__class__.__name__}] skip by regex title matched: {pattern}")
                return False
        return True

    async def dispatch(
        self, request: Request, call_next: Callable[[Request], Awaitable[Response]]
    ) -> Response | PrettyJSONFeedResponse:
        response = await call_next(request)
        path = request.url.path
        result = re.match(self.__class__.MATCH_URL_PATTERN, path)
        ct = response.headers.get("content-type")
        if ct and ct.startswith("application/feed+json") and result:
            response_body = b""
            async for chunk in response.body_iterator:  # type: ignore
                response_body += chunk
            body = json.loads(response_body)
            headers = dict(response.headers)
            headers.pop("content-length", None)
            if body.get("version") == "https://jsonfeed.org/version/1":
                body["items"] = list(filter(lambda x: self.filter_by_block(x), body["items"]))

            return PrettyJSONFeedResponse(body, status_code=response.status_code, headers=headers)
        return response


class TelegramFeedFilterMiddleware(BaseFeedFilterMiddleware):
    BLOCK_TAG = ["#广告", "#互推", "#频道互推", "#群组互推"]
    BLOCK_CONTENT = [
        "TG必备的搜索引擎，极搜帮你精准找到，想要的群组、频道、音乐 、视频",
        "https://hongxingdl.com",
        "搜 蒸蒸日上 概率有5元猫卡",
        "<code>ikelee</code>",
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


class ExtractHashtagMiddleware(BaseHTTPMiddleware):
    """从 content_text 或 content_html 中提取 hashtag 并写入 tags 字段"""

    HASHTAG_PATTERN = re.compile(r"#(\w+)", re.UNICODE)

    def extract_hashtags(self, payload: dict) -> dict:
        feed = JSONFeedItem.model_validate(payload)
        text = feed.content_text or feed.content_html
        if text:
            found = self.HASHTAG_PATTERN.findall(text)
            if found:
                existing = set(feed.tags or [])
                existing.update(f"#{tag}" for tag in found)
                feed.tags = sorted(existing)
        return feed.model_dump()

    async def dispatch(
        self, request: Request, call_next: Callable[[Request], Awaitable[Response]]
    ) -> Response | PrettyJSONFeedResponse:
        response = await call_next(request)
        ct = response.headers.get("content-type")
        if ct and ct.startswith("application/feed+json") and request.url.path.startswith("/api/rss/"):
            response_body = b""
            async for chunk in response.body_iterator:  # type: ignore
                response_body += chunk
            body = json.loads(response_body)
            headers = dict(response.headers)
            headers.pop("content-length", None)
            if body.get("version") == "https://jsonfeed.org/version/1":
                body["items"] = list(map(self.extract_hashtags, body["items"]))
            return PrettyJSONFeedResponse(body, status_code=response.status_code, headers=headers)
        return response


class FillImageFromAuthorAvatarMiddleware(BaseHTTPMiddleware):
    """当 item.image 不存在且 author.avatar 存在时，用 avatar 填充 image"""

    def fill_image(self, payload: dict):
        feed = JSONFeedItem.model_validate(payload)
        if not feed.image and feed.author and feed.author.avatar:
            feed.image = feed.author.avatar
        return feed.model_dump()

    async def dispatch(
        self, request: Request, call_next: Callable[[Request], Awaitable[Response]]
    ) -> Response | PrettyJSONFeedResponse:
        response = await call_next(request)
        ct = response.headers.get("content-type")
        if ct and ct.startswith("application/feed+json") and request.url.path.startswith("/api/rss/"):
            response_body = b""
            async for chunk in response.body_iterator:  # type: ignore
                response_body += chunk
            body = json.loads(response_body)
            headers = dict(response.headers)
            headers.pop("content-length", None)
            if body.get("version") == "https://jsonfeed.org/version/1":
                body["items"] = list(map(self.fill_image, body["items"]))
            return PrettyJSONFeedResponse(body, status_code=response.status_code, headers=headers)
        return response


class FillFeedIconFromAuthorAvatarMiddleware(BaseHTTPMiddleware):
    """当顶层 author.avatar 存在时，用 avatar 覆盖 icon/favicon"""

    async def dispatch(
        self, request: Request, call_next: Callable[[Request], Awaitable[Response]]
    ) -> Response | PrettyJSONFeedResponse:
        response = await call_next(request)
        ct = response.headers.get("content-type")
        if ct and ct.startswith("application/feed+json") and request.url.path.startswith("/api/rss/"):
            response_body = b""
            async for chunk in response.body_iterator:  # type: ignore
                response_body += chunk
            body = json.loads(response_body)
            headers = dict(response.headers)
            headers.pop("content-length", None)
            author = body.get("author")
            avatar = author.get("avatar") if isinstance(author, dict) else None
            if avatar:
                body["icon"] = avatar
                body["favicon"] = avatar
            return PrettyJSONFeedResponse(body, status_code=response.status_code, headers=headers)
        return response


class FillFeedAuthorFromItemsMiddleware(BaseHTTPMiddleware):
    """当 JSONFeed 顶层 author 不存在时，从 items 中取第一个有 author 的条目填充"""

    async def dispatch(
        self, request: Request, call_next: Callable[[Request], Awaitable[Response]]
    ) -> Response | PrettyJSONFeedResponse:
        response = await call_next(request)
        ct = response.headers.get("content-type")
        if ct and ct.startswith("application/feed+json") and request.url.path.startswith("/api/rss/"):
            response_body = b""
            async for chunk in response.body_iterator:  # type: ignore
                response_body += chunk
            body = json.loads(response_body)
            headers = dict(response.headers)
            headers.pop("content-length", None)
            if body.get("version") == "https://jsonfeed.org/version/1" and not body.get("author"):
                for item in body.get("items", []):
                    if item.get("author"):
                        body["author"] = item["author"]
                        break
            return PrettyJSONFeedResponse(body, status_code=response.status_code, headers=headers)
        return response


class MarkdownRenderMiddleware(BaseHTTPMiddleware):
    """尝试对 content_text 进行 markdown 渲染, 并写进 content_html"""

    def markdown_render(self, payload: dict):
        feed = JSONFeedItem.model_validate(payload)
        if feed.content_text and not feed.content_html:
            try:
                feed.content_html = markdown_parse(feed.content_text)
                feed.content_text = None
            except Exception:
                pass
        return feed.model_dump()

    async def dispatch(
        self, request: Request, call_next: Callable[[Request], Awaitable[Response]]
    ) -> Response | PrettyJSONFeedResponse:
        response = await call_next(request)
        path = request.url.path
        ct = response.headers.get("content-type")
        if ct and ct.startswith("application/feed+json") and path.startswith("/api/rss/"):
            response_body = b""
            async for chunk in response.body_iterator:  # type: ignore
                response_body += chunk
            body = json.loads(response_body)
            headers = dict(response.headers)
            headers.pop("content-length", None)
            if body.get("version") == "https://jsonfeed.org/version/1":
                body["items"] = list(map(self.markdown_render, body["items"]))
            return PrettyJSONFeedResponse(body, status_code=response.status_code, headers=headers)
        return response
