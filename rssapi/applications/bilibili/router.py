from asyncache import cached
from fastapi import APIRouter, Path, Query, Request

from rssapi.applications.bilibili.utils import (
    BILIBILI_FAVICON,
    BILIBILI_SPACE_BASE,
    fetch_user_feed_data,
)
from rssapi.applications.rss.schemas.rss.jsonfeed import JSONFeed
from rssapi.core.responses import PrettyJSONFeedResponse
from rssapi.core.settings import settings
from rssapi.utils.cache import RandomTTLCache

router = APIRouter(tags=["RSS"], prefix="/rss/bilibili")


@router.get(
    "/user/{mid}",
    response_model=JSONFeed,
    summary="Bilibili 用户投稿视频 RSS 订阅",
    response_class=PrettyJSONFeedResponse,
)
async def user_videos(
    req: Request,
    mid: int = Path(..., description="Bilibili 用户 UID/mid", examples=[4186021]),
    page_size: int = Query(30, ge=1, le=50, description="返回视频数量，默认 30，最大 50"),
    use_cache: bool = Query(True, description="是否从缓存返回"),
):
    """获取 Bilibili 用户最新投稿视频的 JSON Feed。"""
    user, items = (
        await fetch_user_feed_data_by_cache(mid, page_size)
        if use_cache
        else await fetch_user_feed_data(mid, page_size)
    )
    user_name = (user or {}).get("name") or str(mid)
    user_sign = (user or {}).get("sign") or ""
    user_face = (user or {}).get("face") or BILIBILI_FAVICON
    return JSONFeed.model_validate(
        {
            "version": "https://jsonfeed.org/version/1",
            "title": f"{user_name} 的 Bilibili 投稿",
            "description": user_sign,
            "home_page_url": f"{BILIBILI_SPACE_BASE}/{mid}",
            "feed_url": f"{req.url.scheme}://{req.url.hostname}{req.url.path}?{req.url.query}",
            "icon": user_face,
            "favicon": user_face,
            "author": {
                "name": user_name,
                "url": f"{BILIBILI_SPACE_BASE}/{mid}",
                "avatar": user_face,
            },
            "items": items,
        }
    )


@cached(RandomTTLCache(settings.bilibili.user_videos_cache_maxsize, settings.bilibili.user_videos_cache_ttl))
async def fetch_user_feed_data_by_cache(mid: int, page_size: int):
    return await fetch_user_feed_data(mid, page_size)
