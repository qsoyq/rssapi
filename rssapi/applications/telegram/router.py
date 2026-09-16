import asyncio
import logging
from html import escape
from itertools import chain
from typing import Any

from asyncache import cached
from cachetools.keys import hashkey
from fastapi import APIRouter, HTTPException, Path, Query, Request
from fastapi.responses import RedirectResponse

from rssapi.applications.rss.schemas.rss.jsonfeed import JSONFeed, JSONFeedAttachment, JSONFeedItem
from rssapi.applications.telegram.schemas import TelegramMedia
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

        media_items = message.media or [
            TelegramMedia(kind="image", url=url, mime_type="image/jpeg") for url in message.photoUrls or []
        ]
        if media_items:
            attachments: list[JSONFeedAttachment] = []
            media_html: list[str] = []
            for index, media in enumerate(media_items):
                rendered_url = (
                    public_url(
                        req, f"{settings.api_prefix}/rss/telegram/media/{message.channelName}/{message.msgid}/{index}"
                    )
                    if req is not None
                    else str(media.url)
                )
                safe_url = escape(rendered_url, quote=True)
                if media.kind == "video":
                    media_html.append(f'<video controls preload="metadata" src="{safe_url}"></video>')
                    attachments.append(
                        JSONFeedAttachment.model_validate({"url": rendered_url, "mime_type": media.mime_type})
                    )
                else:
                    media_html.append(TelegramToolkit.generate_img_tag(safe_url))
                    if req is not None and payload.get("image") is None:
                        payload["image"] = rendered_url
                        payload["banner_image"] = rendered_url
            payload["content_html"] = f"🖼️ {''.join(media_html)}{payload['content_html']}"
            if attachments:
                payload["attachments"] = attachments

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
    index: int = Path(..., ge=0),
) -> RedirectResponse:
    media_items = await get_message_media(channel, message_id)
    if index >= len(media_items):
        raise HTTPException(status_code=404, detail=f"Telegram message has no media at index {index}: {message_id}")
    return RedirectResponse(str(media_items[index].url), status_code=302, headers={"Cache-Control": "no-store"})


@cached(
    RandomTTLCache(settings.telegram.media_cache_maxsize, settings.telegram.media_cache_ttl),
    key=lambda channel, message_id: hashkey(channel, message_id),
)
async def get_message_media(channel: str, message_id: str) -> list[TelegramMedia]:
    try:
        return await TelegramToolkit.get_message_media(
            channel,
            message_id,
            base_url=settings.telegram.media_base_url,
            timeout=settings.telegram.media_request_timeout,
            retries=settings.telegram.media_retry_count,
        )
    except LookupError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    except TimeoutError as exc:
        raise HTTPException(status_code=504, detail=str(exc)) from exc
    except (ConnectionError, RuntimeError) as exc:
        raise HTTPException(status_code=502, detail=str(exc)) from exc


@cached(RandomTTLCache(settings.telegram.cache_maxsize, settings.telegram.cache_ttl))
async def get_channel_messages(channelName: str):
    return await TelegramToolkit.get_channel_messages(channelName)
