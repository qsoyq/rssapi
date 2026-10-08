import logging

from fastapi import APIRouter, Request

from rssapi.applications.rss.schemas.rss.jsonfeed import JSONFeed, JSONFeedItem
from rssapi.core.responses import PrettyJSONFeedResponse

router = APIRouter(tags=["RSS"], prefix="/rss")

logger = logging.getLogger(__file__)

content_html = """
<p>这是一条用于展示 JSON Feed 格式的示例作品，不包含真实人物信息。</p>
<p><a href="https://example.com/videos/sample-video">查看示例作品</a></p>
"""


@router.get(
    "/jsonfeed/example", response_model=JSONFeed, summary="JSONFeed 示例", response_class=PrettyJSONFeedResponse
)
async def jsonfeed(
    req: Request,
):
    """jsonfeed example"""

    host = req.url.hostname
    items: list[JSONFeedItem] = []
    feed = {
        "version": "https://jsonfeed.org/version/1",
        "title": "JSON Feed 示例",
        "description": "通用视频订阅示例",
        "home_page_url": "https://example.com",
        "feed_url": f"{req.url.scheme}://{host}{req.url.path}?{req.url.query}",
        "icon": "https://example.com/favicon.ico",
        "favicon": "https://example.com/favicon.ico",
        "items": items,
    }

    payload = {
        "author": {
            "url": "https://example.com/users/sample_user",
            "name": "示例作者",
            "avatar": "https://example.com/avatar.jpg",
        },
        "url": "https://example.com/videos/sample-video",
        "title": "示例视频",
        "id": "sample-video",
        "date_published": "2025-08-08 06:00:00 CST",
        "content_html": content_html,
    }
    items.append(JSONFeedItem.model_validate(payload))
    return feed
