import json
import logging
from collections.abc import Awaitable, Callable

from asyncache import cached
from fastapi import HTTPException

from rssapi.applications.rss.schemas.rss.jsonfeed import JSONFeedItem
from rssapi.applications.twitter.types import Tweet
from rssapi.applications.twitter.utils import (
    AuthorScreenNameMapping,
    content_html_from_tweet,
    fetch_feed,
    fetch_user_posts,
    text_without_http_links,
    title_from_text_by_delimiter_priority,
)
from rssapi.utils.cache import RandomTTLCache

logger = logging.getLogger(__file__)


def _avatar_from_tweet(tweet: Tweet) -> str | None:
    """优先从推文里读取图片作为头像，如果没有则从作者的 profile image url 读取"""
    photos = [media.url for media in tweet.media if media.type == "photo"]
    return photos[0] if photos else tweet.author.profile_image_url


def _tweets_to_jsonfeed_items(tweets: list[Tweet]) -> list[JSONFeedItem]:
    items = []
    for tweet in tweets:
        AuthorScreenNameMapping.set(tweet.author.name, tweet.author.screen_name)
        title = text_without_http_links(tweet.text)
        title = title_from_text_by_delimiter_priority(title)
        items.append(
            JSONFeedItem.model_validate(
                {
                    "id": tweet.id,
                    "url": f"https://x.com/{tweet.author.screen_name}/status/{tweet.id}",
                    "title": title,
                    "content_html": content_html_from_tweet(tweet),
                    "date_published": tweet.created_at,
                    "author": {
                        "name": tweet.author.name,
                        "url": f"https://x.com/{tweet.author.screen_name}",
                        "avatar": _avatar_from_tweet(tweet),
                    },
                }
            )
        )
    return items


async def _fetch_and_convert(
    fetcher: Callable[[], Awaitable[list[Tweet]]],
    label: str,
) -> list[JSONFeedItem]:
    try:
        posts = await fetcher()
    except json.JSONDecodeError as e:
        logger.error(f"failed to parse twitter CLI output: {e}")
        raise HTTPException(status_code=500, detail="Failed to parse twitter CLI output")
    except Exception as e:
        logger.error(f"failed to fetch {label}: {e}")
        status_code = 429 if "429" in str(e) else 500
        raise HTTPException(status_code=status_code, detail=str(e))
    logger.info(f"fetched {len(posts)} tweets for {label}")

    if len(posts) == 0:
        raise HTTPException(status_code=404, detail="No posts found")

    return _tweets_to_jsonfeed_items(posts)


@cached(RandomTTLCache(4096, 7200))
async def fetch_user_posts_jsonfeed_items(screen_name: str, max_tweets: int) -> list[JSONFeedItem]:
    return await _fetch_and_convert(lambda: fetch_user_posts(screen_name, max_tweets), f"user posts ({screen_name})")


@cached(RandomTTLCache(4096, 3600))
async def fetch_feed_jsonfeed_items(max_tweets: int, cookies: str, feed_type: str) -> list[JSONFeedItem]:
    return await _fetch_and_convert(lambda: fetch_feed(max_tweets, cookies, feed_type), f"feed ({feed_type})")
