import logging
from typing import Any, cast

import httpx
from fastapi import APIRouter, HTTPException, Path, Query, Request

from rssapi.applications.f50.schemas import Message
from rssapi.applications.f50.utils import SMS
from rssapi.applications.rss.schemas.rss.jsonfeed import JSONFeed, JSONFeedItem
from rssapi.core.responses import PrettyJSONFeedResponse

router = APIRouter(tags=["RSS"], prefix="/rss/f50")

logger = logging.getLogger(__file__)


@router.get(
    "/sms/{password}", summary="F50 短信 RSS 订阅", response_model=JSONFeed, response_class=PrettyJSONFeedResponse
)
async def sms_list(
    req: Request,
    password: str = Path(..., description="编码后的字符串"),
    number: str | None = Query(None, description="按照号码过滤"),
):
    """f50 短信订阅"""
    items: list[JSONFeedItem] = []
    feed = {
        "version": "https://jsonfeed.org/version/1",
        "title": "F50 - 短信订阅",
        "description": "",
        "home_page_url": "http://192.168.0.1/index.html",
        "feed_url": f"{req.url.scheme}://{req.url.hostname}{req.url.path}?{req.url.query}",
        "icon": "https://www.zte.com.cn/favicon.ico",
        "favicon": "https://www.zte.com.cn/favicon.ico",
        "items": items,
    }

    sms = SMS(password)
    try:
        await sms.login()
    except httpx.RemoteProtocolError:
        raise HTTPException(status_code=502, detail="device maybe closed")
    messages: list[Message] = await sms.get_sms_list()

    messages.sort(key=lambda x: -cast(int, x.timestamp))
    if number is not None:
        messages = [x for x in messages if x.number == number]

    for message in messages:
        payload: dict[str, Any] = {
            "url": "http://192.168.0.1/index.html#sms",
            "title": f"{message.number}",
            "id": f"f50-sms-{message.id} - {message.date}",
            "date_published": message.date,
            "content_text": message.content,
        }
        items.append(JSONFeedItem(**payload))

    return feed
