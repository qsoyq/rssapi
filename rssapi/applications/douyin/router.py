import asyncio
import json
import logging
from typing import cast

import httpx
from asyncache import cached
from fastapi import APIRouter, Header, HTTPException, Path, Query, Request
from playwright._impl._errors import TimeoutError as PlaywrightTimeoutError

from rssapi.applications.douyin.search import DouyinSearchError, DouyinTopicClient
from rssapi.applications.douyin.utils import (
    install_log_redaction,
    normalize_topic,
    resolve_cookie,
    topic_page_url,
    topic_posts_to_feeds,
)
from rssapi.applications.rss.schemas.rss.jsonfeed import JSONFeed, JSONFeedItem
from rssapi.core.responses import PrettyJSONFeedResponse
from rssapi.core.settings import AppSettings, settings
from rssapi.utils.cache import RandomTTLCache
from rssapi.utils.playwright import logger as playwright_logger
from rssapi.utils.playwright_capacity import PlaywrightCapacityError
from rssapi.utils.rss.douyin import AccessHistory, DouyinPlaywright, TimeoutException, to_feeds
from rssapi.utils.urls import public_request_url

rss_douyin_user_semaphore = asyncio.locks.Semaphore(AppSettings().rss_douyin_user_semaphore)

router = APIRouter(tags=["RSS"], prefix="/rss/douyin")

logger = logging.getLogger(__file__)
install_log_redaction(playwright_logger)

user_feeds_cache = RandomTTLCache(settings.douyin.user_feeds_cache_maxsize, settings.douyin.user_feeds_cache_ttl)
topic_feeds_cache = RandomTTLCache(settings.douyin.topic_feeds_cache_maxsize, settings.douyin.topic_feeds_cache_ttl)


@router.get(
    "/user/{username:str}",
    summary="抖音用户作品订阅",
    response_model=JSONFeed,
    response_class=PrettyJSONFeedResponse,
)
async def user(
    req: Request,
    username: str = Path(
        ..., description="用户主页 id", examples=["MS4wLjABAAAAv4fFOLeoSQ9g8Mnc0mfPq0P6Gm14KBm2-p5sNVsdXhM"]
    ),
    timeout: float = Query(60, description="执行抖音内容抓取的超时时间"),
    use_cache: bool = Query(True, description="是否从缓存返回"),
    cookies: str | None = Query(None, description="抖音完整 Cookie，也可通过 X-Douyin-Cookie 请求头传递"),
    x_douyin_cookie: str | None = Header(None, alias="X-Douyin-Cookie", description="抖音完整 Cookie；优先于 query"),
):
    """
    <pre class="mermaid">
        flowchart TB
            A[请求抖音用户作品数据开始] --> B{是否存在未过期的缓存?}
            B -->|YES| C[返回缓存结果]
            B -->|NO| D[超时检测上下文]
            D -->|超时| E[返回 504 超时响应]
            D -->|未超时| D2[无头浏览器Playwright]
            subgraph 无头浏览器获取用户作品
                direction LR
                D2-->F[打开用户主页]
                F -->|监听/web/aweme/post| G[获取用户作品数据]
                G --> H[生成 Feeds 数据]
                H --> I[写入缓存结果]
                H --> J[构造 JSONFeed]
            end
            J --> K[返回200]
    </pre>
    """
    cookie = resolve_cookie(cookies, x_douyin_cookie)
    return await _get_douyin_user_videos(req, username, timeout, use_cache, cookie=cookie)


@router.get(
    "/user/{username:str}/{sessionid_ss:str}",
    summary="抖音用户作品订阅",
    response_model=JSONFeed,
    response_class=PrettyJSONFeedResponse,
)
async def user_with_cookie(
    req: Request,
    username: str = Path(
        ..., description="用户主页 id", examples=["MS4wLjABAAAAv4fFOLeoSQ9g8Mnc0mfPq0P6Gm14KBm2-p5sNVsdXhM"]
    ),
    sessionid_ss: str = Path(..., description="用户 Cookie"),
    timeout: float = Query(60, description="执行内容获取的超时时间"),
    use_cache: bool = Query(True, description="是否从缓存返回"),
):
    """
    <pre class="mermaid">
        flowchart TB
            A[请求抖音用户作品数据开始] --> B{是否存在未过期的缓存?}
            B -->|YES| C[返回缓存结果]
            B -->|NO| D[超时检测上下文]
            D -->|超时| E[返回 504 超时响应]
            D -->|未超时| D2[无头浏览器Playwright]
            subgraph 无头浏览器获取用户作品
                direction LR
                D2-->F[打开用户主页]
                F -->|监听/web/aweme/post| G[获取用户作品数据]
                G --> H[生成 Feeds 数据]
                H --> I[写入缓存结果]
                H --> J[构造 JSONFeed]
            end
            J --> K[返回200]
    </pre>
    """
    return await _get_douyin_user_videos(req, username, timeout, use_cache, sessionid_ss)


async def _get_douyin_user_videos(
    req: Request,
    username: str,
    timeout: float,
    use_cache: bool,
    sessionid_ss: str | None = None,
    *,
    cookie: str | None = None,
):
    items: list[JSONFeedItem] = []
    feed = {
        "version": "https://jsonfeed.org/version/1",
        "title": "抖音用户作品RSS订阅",
        "description": "",
        "home_page_url": f"https://www.douyin.com/user/{username}",
        "feed_url": (
            f"{req.url.scheme}://{req.url.hostname}{req.url.path}?{req.url.query}"
            if sessionid_ss is not None
            else public_request_url(req, remove_query_params={"cookies"})
        ),
        "icon": "https://www.douyin.com/favicon.ico",
        "favicon": "https://www.douyin.com/favicon.ico",
        "items": items,
    }
    if sessionid_ss is not None:
        cookie = f"sessionid_ss={sessionid_ss}" if sessionid_ss else None
    try:
        async with asyncio.timeout(timeout):
            items = await get_feeds_by_cache(username, cookie) if use_cache else await get_feeds(username, cookie)
    except PlaywrightCapacityError as exc:
        raise HTTPException(
            status_code=503,
            detail="Playwright capacity is exhausted",
            headers={"Retry-After": "5"},
        ) from exc
    except (asyncio.TimeoutError, TimeoutException, TimeoutError, PlaywrightTimeoutError):
        raise HTTPException(status_code=504, detail="获取数据超时")
    douyin_user_feeds_handler(feed, items)
    return feed


def douyin_user_feeds_handler(feed: dict, items: list[JSONFeedItem]):
    if items and items[0].author:
        feed["title"] = items[0].author.name
        feed["author"] = items[0].author

    if items and items[0].author and items[0].author.avatar:
        feed["icon"] = feed["favicon"] = items[0].author.avatar

    for item in items:
        if item.image and item.author:
            item.author.avatar = item.image
    feed["items"] = items


@cached(user_feeds_cache)
async def get_feeds_by_cache(username: str, cookie: str | None) -> list[JSONFeedItem]:
    return await get_feeds(username, cookie)


async def get_feeds(username: str, cookie: str | None) -> list[JSONFeedItem]:
    async with rss_douyin_user_semaphore:
        if cookie:
            await AccessHistory.append(username, cookie)

        url = f"https://www.douyin.com/user/{username}"
        play = DouyinPlaywright(url)
        if cookie is not None:
            cookies = play.cookies_by_str(cookie, "https://www.douyin.com")
            play.add_cookies(cookies)
        try:
            result = await play.run()
        except json.decoder.JSONDecodeError:
            raise HTTPException(500, detail="fetch user feed failed")
        items = to_feeds(username, result)
        return cast(list[JSONFeedItem], items)


@router.get(
    "/topic/{topic}",
    summary="抖音话题最新作品订阅",
    response_model=JSONFeed,
    response_class=PrettyJSONFeedResponse,
)
async def topic(
    req: Request,
    topic: str = Path(..., min_length=1, max_length=100, description="话题名，可带 #；# 在 URL 中需编码为 %23"),
    cookies: str | None = Query(None, description="抖音完整 Cookie，也可通过 X-Douyin-Cookie 请求头传递"),
    x_douyin_cookie: str | None = Header(None, alias="X-Douyin-Cookie", description="抖音完整 Cookie；优先于 query"),
    max_posts: int = Query(30, ge=1, le=45, description="最多返回的作品数；最多抓取三页，过滤后可能不足"),
    timeout: float = Query(60, gt=0, le=180, description="包括排队、会话初始化和分页的总超时秒数"),
    use_cache: bool = Query(True, description="是否从缓存返回"),
):
    normalized_topic = normalize_topic(topic)
    cookie = resolve_cookie(cookies, x_douyin_cookie)
    try:
        async with asyncio.timeout(timeout):
            items = (
                await fetch_topic_feeds_by_cache(normalized_topic, cookie, max_posts)
                if use_cache
                else await fetch_topic_feeds(normalized_topic, cookie, max_posts)
            )
    except PlaywrightCapacityError as exc:
        raise HTTPException(503, detail="Playwright capacity is exhausted", headers={"Retry-After": "5"}) from exc
    except (TimeoutError, PlaywrightTimeoutError, httpx.TimeoutException):
        raise HTTPException(504, detail="获取数据超时") from None
    except DouyinSearchError as exc:
        headers = {"Retry-After": "60"} if exc.status_code == 503 else None
        raise HTTPException(exc.status_code, detail=str(exc), headers=headers) from None
    return {
        "version": "https://jsonfeed.org/version/1",
        "title": f"抖音话题 #{normalized_topic} · 最新发布",
        "description": f"明确带 #{normalized_topic} 的视频和图文，按发布时间排序",
        "home_page_url": topic_page_url(normalized_topic),
        "feed_url": public_request_url(req, remove_query_params={"cookies"}),
        "author": {"name": "抖音话题订阅", "url": topic_page_url(normalized_topic)},
        "icon": "https://www.douyin.com/favicon.ico",
        "favicon": "https://www.douyin.com/favicon.ico",
        "items": [item.model_copy(deep=True) for item in items],
    }


def _topic_semaphore() -> asyncio.Semaphore:
    loop = asyncio.get_running_loop()
    attribute = "_rssapi_douyin_topic_semaphore"
    semaphore = getattr(loop, attribute, None)
    if not isinstance(semaphore, asyncio.Semaphore):
        semaphore = asyncio.Semaphore(settings.douyin.topic_fetch_concurrency)
        setattr(loop, attribute, semaphore)
    return semaphore


@cached(topic_feeds_cache)
async def fetch_topic_feeds_by_cache(
    topic: str, cookie: str, max_posts: int = 30, *, client: DouyinTopicClient | None = None
) -> list[JSONFeedItem]:
    return await fetch_topic_feeds(topic, cookie, max_posts, client=client)


async def fetch_topic_feeds(
    topic: str, cookie: str, max_posts: int = 30, *, client: DouyinTopicClient | None = None
) -> list[JSONFeedItem]:
    async with _topic_semaphore():
        posts = await (client or DouyinTopicClient()).fetch(topic, cookie, max_posts)
        return topic_posts_to_feeds(topic, posts)[:max_posts]
