import logging

from fastapi import APIRouter, HTTPException, Path, Query, Request

from rssapi.applications.rss.schemas.rss.jsonfeed import JSONFeed
from rssapi.applications.youtube.utils import fetch_channel_feed, fetch_channel_info_by_handle

router = APIRouter(tags=["RSS"], prefix="/rss/youtube")

logger = logging.getLogger(__file__)


@router.get("/channel/{handle}", response_model=JSONFeed, summary="YouTube 频道视频 RSS 订阅")
def _(
    handle: str = Path(..., description="YouTube 频道 handle，如 `@zhongwenze`"),
    max_results: int = Query(20, ge=1, le=50, description="返回视频数量，默认 20，最大 50"),
):
    """获取 YouTube 频道最新视频的 JSON Feed

    通过 YouTube Data API V3 查询频道视频列表并转换为 JSON Feed 格式。

    用于在 swagger ui 工具构造请求, 没有实际意义
    """
    raise HTTPException(status_code=400, detail="Not implemented")


@router.get("/channel/{handle}/{api_key}", response_model=JSONFeed, summary="YouTube 频道视频 RSS 订阅")
def channel_feed(
    req: Request,
    handle: str = Path(..., description="YouTube 频道 handle，如 `@zhongwenze`"),
    api_key: str = Path(..., description="YouTube API Key"),
    max_results: int = Query(20, ge=1, le=50, description="返回视频数量，默认 20，最大 50"),
):
    """获取 YouTube 频道最新视频的 JSON Feed

    通过 YouTube Data API V3 查询频道视频列表并转换为 JSON Feed 格式。
    """
    raise HTTPException(status_code=400, detail="Not implemented")
    items = []

    channel = fetch_channel_info_by_handle(api_key, handle)
    if channel is not None:
        items = fetch_channel_feed(api_key, handle, max_results)

    feed = JSONFeed.model_validate(
        {
            "version": "https://jsonfeed.org/version/1",
            "title": channel["title"] if channel else "",
            "description": channel["description"] if channel else "",
            "home_page_url": f"https://www.youtube.com/channel/{channel['id']}"
            if channel
            else "https://www.youtube.com",
            "feed_url": f"{req.url.scheme}://{req.url.hostname}{req.url.path}?{req.url.query}",
            "icon": channel["thumbnails"] if channel else "",
            "favicon": channel["thumbnails"] if channel else "",
            "items": items,
        }
    )

    return feed
