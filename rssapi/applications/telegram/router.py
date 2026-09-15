import asyncio
import logging
from itertools import chain
from typing import Any

from asyncache import cached
from fastapi import APIRouter, HTTPException, Path, Query, Request
from fastapi.responses import RedirectResponse

from rssapi.applications.rss.schemas.rss.jsonfeed import JSONFeed, JSONFeedItem
from rssapi.core.responses import PrettyJSONFeedResponse
from rssapi.core.settings import settings
from rssapi.utils.basic import TelegramToolkit
from rssapi.utils.cache import RandomTTLCache
from rssapi.utils.md import markdown_parse
from rssapi.utils.urls import public_request_url, public_url

router = APIRouter(tags=["RSS"], prefix="/rss/telegram")

logger = logging.getLogger(__file__)


@router.get(
    "/channel",
    summary="Telegram Channel RSS Subscribe",
    response_model=JSONFeed,
    response_class=PrettyJSONFeedResponse,
)
async def channel_jsonfeed(req: Request, channels: list[str] = Query(..., description="channel name")):
    """Telegram Channel RSS Subscribe"""
    items = await fetch_feeds(channels, req=req)
    feed: dict[str, Any] = {
        "version": "https://jsonfeed.org/version/1",
        "title": "Telegram Channel RSS Subscribe",
        "description": "",
        "home_page_url": "https://t.me",
        "feed_url": public_request_url(req),
        "icon": "https://fastly.jsdelivr.net/gh/Koolson/Qure@master/IconSet/Color/Telegram.png",
        "favicon": "https://fastly.jsdelivr.net/gh/Koolson/Qure@master/IconSet/Color/Telegram.png",
        "items": items,
    }
    for item in items:
        if item.author:
            if item.author.avatar:
                feed["icon"] = item.author.avatar
                feed["favicon"] = item.author.avatar
            if item.author.name:
                feed["title"] = item.author.name
            feed["author"] = item.author
            break

    return feed


async def fetch_feeds(channels: list[str], *, req: Request | None = None) -> list[JSONFeedItem]:
    items = []
    tasks = await asyncio.gather(*[get_channel_messages(channelName) for channelName in channels])
    for message in chain(*tasks):
        if message.contentHtml:
            try:
                message.contentHtml = markdown_parse(message.contentHtml)
            except Exception as e:
                logger.warning(f"convert markdown to html failed: {e}")
        payload = {
            "id": f"{message.channelName}-{message.msgid}",
            "title": f"{message.title}",
            "url": f"https://t.me/{message.channelName}/{message.msgid}",
            "date_published": message.updated,
            "content_html": message.contentHtml or "",
            "tags": message.tags,
            "author": {
                "avatar": message.head,
                "name": message.channelName,
                "url": f"https://t.me/{message.channelName}",
            },
        }

        if message.photoUrls:
            payload["image"] = message.photoUrls[0]
            payload["banner_image"] = message.photoUrls[0]
            photosOuterHTML = ""
            for index, url in enumerate(message.photoUrls):
                rendered_url = (
                    public_url(
                        req, f"{settings.api_prefix}/rss/telegram/media/{message.channelName}/{message.msgid}/{index}"
                    )
                    if req is not None
                    else str(url)
                )
                tag = TelegramToolkit.generate_img_tag(rendered_url)
                photosOuterHTML = f"{photosOuterHTML}{tag}"
            payload["content_html"] = f"🖼️ {photosOuterHTML}{payload['content_html']}"
            if req is not None:
                stable_url = public_url(
                    req, f"{settings.api_prefix}/rss/telegram/media/{message.channelName}/{message.msgid}/0"
                )
                payload["image"] = stable_url
                payload["banner_image"] = stable_url

        items.append(JSONFeedItem(**payload))

    return items


@router.get(
    "/media/{channel}/{message_id}/{index}",
    summary="Telegram 图片稳定重定向",
    response_class=RedirectResponse,
)
async def media(
    channel: str = Path(..., min_length=1, max_length=128, pattern=r"^[A-Za-z0-9_]+$"),
    message_id: str = Path(..., pattern=r"^\d+$"),
    index: int = Path(..., ge=0, le=9),
) -> RedirectResponse:
    messages = await TelegramToolkit.get_channel_messages(channel)
    message = next((item for item in messages if str(item.msgid) == message_id), None)
    if message is None:
        raise HTTPException(status_code=404, detail=f"Telegram message not found: {channel}/{message_id}")
    if not message.photoUrls or index >= len(message.photoUrls):
        raise HTTPException(status_code=404, detail=f"Telegram message has no image at index {index}: {message_id}")
    return RedirectResponse(str(message.photoUrls[index]), status_code=302, headers={"Cache-Control": "no-store"})


@cached(RandomTTLCache(settings.telegram.cache_maxsize, settings.telegram.cache_ttl))
async def get_channel_messages(channelName: str):
    return await TelegramToolkit.get_channel_messages(channelName)
