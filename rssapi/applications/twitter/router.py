import json
import logging
from typing import Any

from asyncache import cached
from fastapi import APIRouter, HTTPException, Path, Query, Request

from rssapi.applications.rss.schemas.rss.jsonfeed import JSONFeed, JSONFeedItem
from rssapi.applications.twitter.utils import (
    AuthorScreenNameMapping,
    content_html_from_tweet,
    fetch_user_posts,
    text_without_http_links,
    title_from_text_by_delimiter_priority,
)
from rssapi.utils.cache import RandomTTLCache

router = APIRouter(tags=["RSS"], prefix="/rss/twitter")

logger = logging.getLogger(__file__)


@cached(RandomTTLCache(4096, 7200))
async def fetch_jsonfeed_items(screen_name: str, max_tweets: int) -> list[JSONFeedItem]:
    items = []
    try:
        posts = await fetch_user_posts(screen_name, max_tweets)
    except json.JSONDecodeError as e:
        logger.error(f"failed to parse twitter CLI output: {e}")
        raise HTTPException(status_code=500, detail="Failed to parse twitter CLI output")
    except Exception as e:
        logger.error(f"failed to fetch twitter user posts: {e}")
        raise HTTPException(status_code=500, detail="Failed to fetch twitter user posts")
    logger.info(f"fetched {len(posts)} posts for {screen_name}")

    if len(posts) == 0:
        raise HTTPException(status_code=404, detail="No posts found")

    for tweet in posts:
        AuthorScreenNameMapping.set(tweet.author.name, tweet.author.screen_name)
        title = tweet.text
        title = text_without_http_links(title)
        title = title_from_text_by_delimiter_priority(title)
        items.append(
            JSONFeedItem.model_validate(
                {
                    "id": tweet.id,
                    "url": f"https://x.com/{screen_name}/status/{tweet.id}",
                    "title": title,
                    "content_html": content_html_from_tweet(tweet),
                    "date_published": tweet.created_at,
                    "author": {
                        "name": tweet.author.name,
                        "url": f"https://x.com/{tweet.author.screen_name}",
                        "avatar": tweet.author.profile_image_url,
                    },
                }
            )
        )
    return items


@router.get("/{screen_name}/posts", response_model=JSONFeed, summary="Twitter User Posts RSS")
async def posts(
    req: Request,
    screen_name: str = Path(..., description="Twitter 用户名"),
    max_tweets: int = Query(50, description="最大推文数"),
):
    """Twitter Timeline RSS"""
    items = await fetch_jsonfeed_items(screen_name, max_tweets)
    host = req.url.hostname
    feed: dict[str, Any] = {
        "version": "https://jsonfeed.org/version/1",
        "title": screen_name,
        "description": "",
        "home_page_url": f"https://x.com/{screen_name}",
        "feed_url": f"{req.url.scheme}://{host}{req.url.path}?{req.url.query}",
        "icon": "https://abs.twimg.com/favicons/twitter-pip.3.ico",
        "favicon": "https://abs.twimg.com/favicons/twitter-pip.3.ico",
        "items": items,
    }
    for item in items:
        if item.author and item.author.name:
            _screen_name = AuthorScreenNameMapping.get(item.author.name)
            if _screen_name is not None and _screen_name == screen_name:
                feed["author"] = item.author
                feed["title"] = item.author.name
                feed["icon"] = feed["favicon"] = item.author.avatar
                break

    return feed
