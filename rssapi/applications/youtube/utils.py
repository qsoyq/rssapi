import logging
from functools import lru_cache
from typing import TypedDict

from cachetools import TTLCache, cached
from googleapiclient.discovery import build

from rssapi.applications.rss.schemas.rss.jsonfeed import JSONFeedItem

logger = logging.getLogger(__file__)

_channel_feed_cache: TTLCache = TTLCache(maxsize=4096, ttl=600)


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


def search_channel_videos(
    api_key: str,
    channel_id: str,
    max_results: int = 20,
    page_token: str | None = None,
) -> list[YoutubeVideoSnippet]:
    """通过 search API 获取频道最新视频列表"""
    youtube = _get_youtube_service(api_key)
    request = youtube.search().list(
        part="snippet",
        channelId=channel_id,
        order="date",
        type="video",
        maxResults=max_results,
        pageToken=page_token or "",
    )
    result = request.execute()
    videos: list[YoutubeVideoSnippet] = []
    for item in result.get("items", []):
        video: YoutubeVideoSnippet = {
            "id": item["id"]["videoId"],
            "title": item["snippet"]["title"],
            "description": item["snippet"]["description"],
            "thumbnails": item["snippet"]["thumbnails"]["high"]["url"],
            "publishedAt": item["snippet"]["publishedAt"],
        }
        videos.append(video)
    return videos


def fetch_channel_info_by_handle(api_key: str, handle: str) -> YoutubeChannelSnippet | None:
    """通过 YouTube handle（如 @zhongwenze）获取频道信息"""
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


@cached(cache=_channel_feed_cache)
def fetch_channel_feed(api_key: str, handle: str, max_results: int = 10) -> list[JSONFeedItem]:
    items = []
    channel = fetch_channel_info_by_handle(api_key, handle)
    if channel is None:
        return []
    videos: list[YoutubeVideoSnippet] = search_channel_videos(api_key, channel["id"], max_results=max_results)
    items = [video_to_jsonfeed_item(channel, video) for video in videos]
    return items


def video_to_jsonfeed_item(channel: YoutubeChannelSnippet, video: YoutubeVideoSnippet) -> JSONFeedItem:
    return JSONFeedItem.model_validate(
        {
            "id": f"youtube-video-{video['id']}",
            "url": f"https://www.youtube.com/watch?v={video['id']}",
            "title": video["title"],
            "content_html": video["description"],
            "date_published": video["publishedAt"],
            "image": video["thumbnails"],
            "author": {
                "name": channel["title"],
                "url": f"https://www.youtube.com/channel/{channel['id']}",
                "avatar": channel["thumbnails"],
            },
        }
    )
