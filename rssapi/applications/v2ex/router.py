import asyncio
import logging
from typing import Any

import httpx
from asyncache import cached
from fastapi import APIRouter, Header, HTTPException, Path, Query, Request

from rssapi.applications.rss.schemas.rss.jsonfeed import JSONFeed, JSONFeedItem
from rssapi.applications.v2ex.schemas.notification import Notification
from rssapi.applications.v2ex.utils import (
    get_title_from_notification_text,
    get_topics,
    get_url_from_notification_text,
)
from rssapi.core.responses import PrettyJSONFeedResponse
from rssapi.utils.basic import get_date_string_for_shanghai
from rssapi.utils.cache import RandomTTLCache

router = APIRouter(tags=["RSS"], prefix="/rss/jsonfeed/v2ex")

logger = logging.getLogger(__file__)


@cached(RandomTTLCache(4096, 600))
async def fetch_jsonfeed_items(topic: str) -> list[JSONFeedItem]:
    url = f"https://www.v2ex.com/feed/{topic}.json"
    try:
        async with httpx.AsyncClient() as client:
            resp = await client.get(url, timeout=30)
    except httpx.TimeoutException:
        logger.warning(f"[V2ex.RSS.Aggregation] request timeout, topic: {topic}")
        return []
    if resp.is_error:
        logger.warning(f"[V2ex.RSS.Aggregation] request error, text: {resp.text}")
        return []
    return [JSONFeedItem(**x) for x in resp.json()["items"]]


@router.get(
    "/aggregation", response_model=JSONFeed, summary="V2ex 节点 RSS 订阅聚合", response_class=PrettyJSONFeedResponse
)
async def aggregation(req: Request, topics: list[str] = Query([], description="订阅主题, 如 wechat、design")):
    """RSS 聚合

    https://www.v2ex.com/feed/{topic}.json
    """
    host = req.url.hostname
    items: list[JSONFeedItem] = []
    feed = {
        "version": "https://jsonfeed.org/version/1",
        "title": "V2ex RSS 订阅聚合",
        "description": "",
        "home_page_url": "https://v2ex.com",
        "feed_url": f"{req.url.scheme}://{host}{req.url.path}?{req.url.query}",
        "icon": "https://www.v2ex.com/favicon.ico",
        "favicon": "https://www.v2ex.com/favicon.ico",
        "items": items,
    }
    if len(topics) == 1:
        feed["home_page_url"] = f"https://v2ex.com/go/{topics[0]}"
    tasks: list[asyncio.Task[list[JSONFeedItem]]] = []
    async with asyncio.TaskGroup() as tg:
        tasks = [tg.create_task(fetch_jsonfeed_items(topic)) for topic in topics]

    items = [item for task in tasks for item in task.result()]
    feed["items"] = items
    return feed


def _resolve_favorite_session_key(session_key: str | None, x_v2ex_session_key: str | None) -> str:
    # V2ex 登录态来自 cookies 里的 A2 字段；query 与 header 二选一，且 header 优先。
    effective_session_key = x_v2ex_session_key if x_v2ex_session_key is not None else session_key
    if effective_session_key is None:
        raise HTTPException(
            status_code=422,
            detail=(
                "V2ex session key from cookies.A2 is required via query parameter `session_key` "
                "or header `X-V2ex-Session-Key`"
            ),
        )
    return effective_session_key


@router.get(
    "/favorite", response_model=JSONFeed, summary="V2ex 收藏帖回复 RSS 订阅", response_class=PrettyJSONFeedResponse
)
def favorite(
    req: Request,
    session_key: str | None = Query(
        None,
        description="来自 V2ex cookies 里的 A2 字段，可与 X-V2ex-Session-Key 二选一；若同时提供则优先使用 X-V2ex-Session-Key",
    ),
    x_v2ex_session_key: str | None = Header(
        None,
        description="来自 V2ex cookies 里的 A2 字段，可与 query 参数 session_key 二选一；若同时提供则优先使用当前请求头",
        alias="X-V2ex-Session-Key",
    ),
    page: int = Query(1, description="收藏页，默认为 1"),
):
    """RSS 收藏贴回复订阅

    python -m pip install git+https://github.com/qsoyq/ai-assistant.git
    ai-assistant cookies get v2ex.com www.v2ex.com --field A2

    https://www.v2ex.com/feed/{topic}.json
    """
    items: list[JSONFeedItem] = []
    feed = {
        "version": "https://jsonfeed.org/version/1",
        "title": "V2ex 收藏帖子RSS订阅",
        "description": "",
        "home_page_url": "https://v2ex.com",
        "feed_url": f"{req.url.scheme}://{req.url.hostname}{req.url.path}?{req.url.query}",
        "icon": "https://www.v2ex.com/favicon.ico",
        "favicon": "https://www.v2ex.com/favicon.ico",
        "items": items,
    }
    ret = get_topics(_resolve_favorite_session_key(session_key, x_v2ex_session_key), page)
    for topic in ret.topics:
        payload = {
            "author": {},
            "url": f"https://v2ex.com/t/{topic.id}",
            "title": f"{topic.title}",
            "id": topic.id,
            "date_published": topic.lastTouchedStr,
            "content_html": "",
        }
        items.append(JSONFeedItem.model_validate(payload))
    return feed


async def build_notifications_feed(req: Request, token: str, page: int) -> JSONFeed:
    items: list[JSONFeedItem] = []
    feed = {
        "version": "https://jsonfeed.org/version/1",
        "title": "V2ex通知提醒",
        "description": "",
        "home_page_url": "https://www.v2ex.com/notifications",
        "feed_url": f"{req.url.scheme}://{req.url.hostname}{req.url.path}?{req.url.query}",
        "icon": "https://www.v2ex.com/favicon.ico",
        "favicon": "https://www.v2ex.com/favicon.ico",
        "items": items,
    }
    headers = {"Authorization": f"Bearer {token}"}
    notifications: list[Notification] = []
    async with httpx.AsyncClient(headers=headers) as client:
        url = "https://www.v2ex.com/api/v2/notifications"
        params = {"p": page}
        resp = await client.get(url, params=params)
        if resp.is_error:
            raise HTTPException(status_code=resp.status_code, detail=resp.text)
        notifications = [Notification.model_validate(x) for x in resp.json()["result"]]

    for item in notifications:
        _url = get_url_from_notification_text(item.text)
        assert _url, item.text

        _title = get_title_from_notification_text(item.text)
        assert _title, item.text
        payload: dict[str, Any] = {
            "author": {},
            "url": _url,
            "title": _title,
            "id": f"{item.id}",
            "date_published": get_date_string_for_shanghai(item.created),
            "content_html": item.payload_rendered,
        }
        items.append(JSONFeedItem.model_validate(payload))
    return JSONFeed.model_validate(feed)


@router.get(
    "/notifications",
    summary="V2ex 个人通知提醒",
    response_model=JSONFeed,
    response_class=PrettyJSONFeedResponse,
)
async def notifications_without_path_token(
    req: Request,
    token: str | None = Query(
        None,
        description="V2ex API Token，可与 X-V2ex-Api-Token 二选一；若同时提供则优先使用 X-V2ex-Api-Token",
    ),
    x_v2ex_api_token: str | None = Header(
        None,
        description="V2ex API Token，可与 query 参数 token 二选一；若同时提供则优先使用当前请求头",
        alias="X-V2ex-Api-Token",
    ),
    page: int = Query(1, description="分页，默认为 1"),
):
    effective_token = x_v2ex_api_token if x_v2ex_api_token is not None else token
    if effective_token is None:
        raise HTTPException(
            status_code=422,
            detail="V2ex API Token is required via query parameter `token` or header `X-V2ex-Api-Token`",
        )

    return await build_notifications_feed(req, effective_token, page)


@router.get(
    "/notifications/{token}",
    summary="V2ex 个人通知提醒",
    response_model=JSONFeed,
    response_class=PrettyJSONFeedResponse,
)
async def notifications(
    req: Request, page: int = Query(1, description="分页，默认为 1"), token: str = Path(..., description="API Token")
):
    return await build_notifications_feed(req, token, page)
