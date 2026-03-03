import logging
import threading
from functools import lru_cache
from typing import TypedDict

import httpx
import xmltodict
from cachetools import TTLCache, cached
from fastapi import HTTPException
from googleapiclient.discovery import build

from rssapi.applications.rss.schemas.rss.jsonfeed import JSONFeedItem
from rssapi.utils.basic import URLToolkit
from rssapi.utils.network import retry_http

logger = logging.getLogger(__file__)

_channel_feed_cache: TTLCache = TTLCache(maxsize=4096, ttl=3600)


class YoutubeChannelSnippet(TypedDict):
    id: str
    title: str
    description: str
    customUrl: str
    thumbnails: str


class YoutubeVideoSnippet(TypedDict):
    id: str
    title: str
    description: str
    thumbnails: str
    publishedAt: str


@lru_cache(maxsize=4)
def _get_youtube_service(api_key: str):
    return build("youtube", "v3", developerKey=api_key)


@retry_http(max_attempts=5, retry_backoff_seconds=0, retry_on_status=lambda status: status >= 300)
def fetch_youtube_rss_xml(url: str) -> httpx.Response:
    return httpx.get(url, timeout=15)


def _fetch_videos_via_rss(channel_id: str, max_results: int = 20) -> list[YoutubeVideoSnippet]:
    """通过 YouTube 公开 RSS Feed 获取频道最新视频，不消耗 API 配额"""
    feed_url = f"https://www.youtube.com/feeds/videos.xml?channel_id={channel_id}"
    resp = fetch_youtube_rss_xml(feed_url)
    if resp.is_error:
        raise HTTPException(status_code=resp.status_code, detail=resp.text)

    data = xmltodict.parse(resp.text)
    entries = data.get("feed", {}).get("entry", [])
    if isinstance(entries, dict):
        entries = [entries]

    videos: list[YoutubeVideoSnippet] = []
    for entry in entries[:max_results]:
        video_id = entry.get("yt:videoId", "")
        media_group = entry.get("media:group", {})
        thumbnail_url = ""
        media_thumbnail = media_group.get("media:thumbnail")
        if isinstance(media_thumbnail, dict):
            thumbnail_url = media_thumbnail.get("@url", "")
        elif isinstance(media_thumbnail, list) and media_thumbnail:
            thumbnail_url = media_thumbnail[0].get("@url", "")

        video: YoutubeVideoSnippet = {
            "id": video_id,
            "title": media_group.get("media:title", entry.get("title", "")),
            "description": media_group.get("media:description", ""),
            "thumbnails": thumbnail_url or f"https://i.ytimg.com/vi/{video_id}/hqdefault.jpg",
            "publishedAt": entry.get("published", ""),
        }
        videos.append(video)
    return videos


@lru_cache(maxsize=4096)
def fetch_channel_info_by_handle(api_key: str, handle: str) -> YoutubeChannelSnippet | None:
    """通过 YouTube handle（如 @zhongwenze）获取频道信息（channels.list 仅消耗 1 单位配额）"""
    youtube = _get_youtube_service(api_key)
    resp = youtube.channels().list(part="snippet,contentDetails", forHandle=handle).execute()
    items = resp.get("items", [])
    if not items:
        return None

    data = items[0]
    snippet: YoutubeChannelSnippet = {
        "id": data["id"],
        "title": data["snippet"]["title"],
        "description": data["snippet"]["description"],
        "customUrl": data["snippet"]["customUrl"],
        "thumbnails": data["snippet"]["thumbnails"]["high"]["url"],
    }
    return snippet


@cached(cache=_channel_feed_cache, lock=threading.Lock())
def fetch_channel_feed(api_key: str, handle: str, max_results: int) -> list[JSONFeedItem]:
    """获取 YouTube 频道最新视频的 JSON Feed"""
    channel = fetch_channel_info_by_handle(api_key, handle)
    if channel is None:
        return []
    videos = _fetch_videos_via_rss(channel["id"], max_results=max_results)
    items = [video_to_jsonfeed_item(channel, video) for video in videos]
    return items


def video_to_jsonfeed_item(channel: YoutubeChannelSnippet, video: YoutubeVideoSnippet) -> JSONFeedItem:
    youtube_video_url = f"https://www.youtube.com/watch?v={video['id']}"
    video_tag = URLToolkit.make_youtube_video(video["id"], video["title"])
    content_html = f"{video_tag}<br>{video['description']}"
    return JSONFeedItem.model_validate(
        {
            "id": f"youtube-video-{video['id']}",
            "url": youtube_video_url,
            "title": video["title"],
            "content_html": content_html,
            "date_published": video["publishedAt"],
            "image": video["thumbnails"],
            "author": {
                "name": channel["title"],
                "url": f"https://www.youtube.com/channel/{channel['id']}",
                "avatar": video["thumbnails"],
            },
        }
    )
