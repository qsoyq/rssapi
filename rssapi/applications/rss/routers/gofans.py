import logging
from datetime import datetime

import httpx
import pytz
from fastapi import APIRouter, HTTPException, Query, Request

from rssapi.applications.rss.schemas.rss.jsonfeed import JSONFeed, JSONFeedItem
from rssapi.core.responses import PrettyJSONFeedResponse
from rssapi.utils.cache import RandomTTLCache, cached

router = APIRouter(tags=["RSS"], prefix="/rss/gofans")

logger = logging.getLogger(__file__)


@router.get(
    "/iOS", response_model=JSONFeed, summary="GoFans App Store iOS 限免RSS订阅", response_class=PrettyJSONFeedResponse
)
async def ios_jsonfeed(
    req: Request,
    limit: int = Query(20),
    page: int = Query(1),
):
    """GoFans App Store iOS 限免RSS订阅"""

    kind = 2
    items = await get_gofans_app_records_by_cache(limit, page, kind)
    feed = {
        "version": "https://jsonfeed.org/version/1",
        "title": "GoFans iOS 应用限免",
        "description": "AppStore iOS 应用限免订阅",
        "home_page_url": "https://gofans.cn/",
        "feed_url": f"{req.url.scheme}://{req.url.hostname}{req.url.path}?{req.url.query}",
        "icon": "https://gofans.cn/favicon.ico",
        "favicon": "https://gofans.cn/favicon.ico",
        "items": items,
    }
    return feed


@router.get(
    "/macOS",
    response_model=JSONFeed,
    summary="GoFans App Store macOS 限免RSS订阅",
    response_class=PrettyJSONFeedResponse,
)
async def macOS_jsonfeed(
    req: Request,
    limit: int = Query(20),
    page: int = Query(1),
):
    """GoFans App Store macOS 限免RSS订阅"""

    kind = 1
    items = await get_gofans_app_records_by_cache(limit, page, kind)
    feed = {
        "version": "https://jsonfeed.org/version/1",
        "title": "GoFans macOS 应用限免",
        "description": "AppStore macOS 应用限免订阅",
        "home_page_url": "https://gofans.cn/",
        "feed_url": f"{req.url.scheme}://{req.url.hostname}{req.url.path}?{req.url.query}",
        "icon": "https://gofans.cn/favicon.ico",
        "favicon": "https://gofans.cn/favicon.ico",
        "items": items,
    }
    return feed


@cached(RandomTTLCache(4096, 3600))
async def get_gofans_app_records_by_cache(limit, page, kind) -> list[JSONFeedItem]:
    items = []
    resp = await get_gofans_app_records(limit, page, kind)
    data = resp.json()
    timezone = pytz.timezone("Asia/Shanghai")
    for item in data.get("data", []):
        description = f"""
            {item["original_price"]} => {item["price"]}
            ✨{item["rating"]}
            {item["description"]}
        """
        description = "\n".join([x.strip() for x in description.split("\n")])
        updated = timezone.localize(datetime.fromtimestamp(item["updated_at"])).strftime("%Y-%m-%d %H:%M:%S%Z")
        url = f"https://gofans.cn/app/{item['uuid']}"
        payload = {
            "url": url,
            "title": f"macOS应用限免: {item['name']}",
            "id": f"macOS-{item['app_id']}",
            "date_published": updated,
            "content_text": description or "",
            "author": {
                "avatar": item["icon"],
                "url": url,
                "name": item["name"],
            },
        }
        items.append(JSONFeedItem.model_validate(payload))
    return items


async def get_gofans_app_records(limit: int, page: int, kind: int) -> httpx.Response:
    headers = {
        "User-Agent": "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/138.0.0.0 Safari/537.36",
        "Accept": "application/json, text/plain, */*",
        "Referer": "https://gofans.cn/",
        "Origin": "https://gofans.cn",
    }
    url = "https://api.gofans.cn/v1/web/app_records"
    params = {"limit": limit, "page": page, "kind": kind}
    resp = httpx.get(url, headers=headers, params=params)
    data = resp.json()
    if data.get("code") == 401:
        logger.warning("[Ics.Gofans] Unauthorized")
        raise HTTPException(502, "Unauthorized")
    return resp
