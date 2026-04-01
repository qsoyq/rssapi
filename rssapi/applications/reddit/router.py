# https://www.reddit.com/r/programming

from datetime import datetime, timezone
from html import escape
from http.cookies import SimpleCookie
from typing import Any
from urllib.parse import urljoin

from fastapi import APIRouter, Header, HTTPException, Path, Query, Request
from fastapi.concurrency import run_in_threadpool
from rdt_cli.auth import Credential
from rdt_cli.client import RedditClient
from rdt_cli.exceptions import RedditApiError

from rssapi.applications.reddit.types import PostData, SubredditAbout, SubredditListing
from rssapi.applications.rss.schemas.rss.jsonfeed import JSONFeed, JSONFeedItem
from rssapi.core.circuit_breaker import circuit_breaker
from rssapi.core.responses import PrettyJSONFeedResponse
from rssapi.utils.cache import RandomTTLCache, cached

router = APIRouter(tags=["RSS"], prefix="/rss/reddit")


@router.get(
    "/subreddit/{subreddit}",
    response_model=JSONFeed,
    summary="Reddit Subreddit Posts RSS",
    response_class=PrettyJSONFeedResponse,
)
@circuit_breaker(status_code=429, cooldown=30)
async def posts(
    req: Request,
    subreddit: str = Path(..., description="Reddit 子版块"),
    max_posts: int = Query(20, description="最大帖子数"),
    cookies: str | None = Query(None, description="Reddit 用户 cookie"),
    x_reddit_cookie: str | None = Header(None, description="Reddit 用户 cookie", alias="X-Reddit-Cookie"),
):
    """Reddit Subreddit Posts RSS"""
    if cookies is None and x_reddit_cookie is not None:
        cookies = x_reddit_cookie

    try:
        about, items = await run_in_threadpool(_fetch_subreddit_feed, subreddit, max_posts, cookies)
    except RedditApiError as exc:
        status_code = exc.code if isinstance(exc.code, int) and 400 <= exc.code < 600 else 502
        raise HTTPException(status_code=status_code, detail=str(exc)) from exc
    except Exception as exc:
        raise HTTPException(status_code=502, detail=f"Failed to fetch subreddit posts: {exc}") from exc

    feed: dict[str, Any] = {
        "version": "https://jsonfeed.org/version/1",
        "title": about.display_name_prefixed or f"r/{subreddit}",
        "description": about.public_description or about.description or about.title or "",
        "home_page_url": f"https://www.reddit.com/r/{subreddit}/",
        "feed_url": str(req.url),
        "icon": "https://www.reddit.com/favicon.ico",
        "favicon": "https://www.reddit.com/favicon.ico",
        "items": items,
    }
    return feed


@cached(RandomTTLCache(4096, 600))
def _fetch_subreddit_feed(
    subreddit: str, max_posts: int, cookies: str | None
) -> tuple[SubredditAbout, list[JSONFeedItem]]:
    credential = _build_credential(cookies)
    with RedditClient(credential) as client:
        about = SubredditAbout.model_validate(client.get_subreddit_about(subreddit))
        listing = SubredditListing.model_validate(client.get_subreddit(subreddit, limit=max_posts))
    children = (listing.data.children or []) if listing.data else []
    items = [_build_feed_item(child.data) for child in children if child.data]
    return about, items


def _build_credential(cookies: str | None) -> Credential | None:
    if not cookies:
        return None

    cookie = SimpleCookie()
    cookie.load(cookies)
    parsed_cookies = {key: morsel.value for key, morsel in cookie.items()}
    if not parsed_cookies:
        return None
    return Credential(cookies=parsed_cookies, source="rssapi")


def _extract_gallery_images(post: PostData) -> list[str]:
    """Extract image URLs from a gallery post's media_metadata, ordered by gallery_data."""
    metadata = post.media_metadata or {}
    gallery_items = (post.gallery_data.items if post.gallery_data else None) or []

    ordered_ids = [item.media_id for item in gallery_items if item.media_id]
    if not ordered_ids:
        ordered_ids = list(metadata.keys())

    urls: list[str] = []
    for media_id in ordered_ids:
        entry = metadata.get(media_id)
        if not entry or entry.status != "valid":
            continue
        source = entry.s
        if not source:
            continue
        url = source.u or source.gif or ""
        if url:
            urls.append(url)
    return urls


def _extract_preview_image(post: PostData) -> str | None:
    """Extract the best-quality preview image URL from a post."""
    if not post.preview or not post.preview.images:
        return None
    first = post.preview.images[0]
    if not first.source:
        return None
    return first.source.url or None


def _extract_video(post: PostData) -> dict[str, str] | None:
    """Extract video URL from a Reddit-hosted or externally-embedded video post."""
    for media in (post.secure_media, post.media):
        if not media:
            continue
        reddit_video = media.get("reddit_video")
        if reddit_video:
            fallback = reddit_video.get("fallback_url") or reddit_video.get("dash_url") or ""
            if fallback:
                return {"type": "reddit", "url": fallback}
        oembed = media.get("oembed")
        if oembed and oembed.get("type") == "video":
            html = oembed.get("html") or ""
            if html:
                return {"type": "oembed", "html": html}
    return None


def _build_feed_item(post: PostData) -> JSONFeedItem:
    reddit_base_url = "https://www.reddit.com"
    post_id = post.id or ""
    title = post.title or ""
    permalink = post.permalink or ""
    url = post.url_overridden_by_dest or post.url or ""
    selftext_html = post.selftext_html or ""
    selftext = post.selftext or ""
    is_self = post.is_self if post.is_self is not None else True
    is_gallery = post.is_gallery or False
    score = post.score or 0
    num_comments = post.num_comments or 0
    author = post.author or ""
    subreddit = post.subreddit or ""
    created_utc = post.created_utc or 0.0

    permalink_url = urljoin(reddit_base_url, permalink) if permalink else None
    target_url = urljoin(reddit_base_url, url) if url else permalink_url

    content_parts: list[str] = []

    if selftext_html:
        content_parts.append(selftext_html)
    elif selftext:
        content_parts.append(f"<p>{escape(selftext).replace(chr(10), '<br>')}</p>")

    video = _extract_video(post)
    if video:
        title = f"▶️ {title}"
        if video["type"] == "reddit":
            vid_url = escape(video["url"], quote=True)
            content_parts.append(f'<video controls preload="metadata" src="{vid_url}"></video>')
        elif video["type"] == "oembed":
            content_parts.append(video["html"])

    if is_gallery:
        gallery_urls = _extract_gallery_images(post)
        if gallery_urls:
            title = f"📸 {title}"
            imgs = "".join(f'<img src="{escape(u, quote=True)}" />' for u in gallery_urls)
            content_parts.append(f"<div>{imgs}</div>")
    elif not video:
        preview_url = _extract_preview_image(post)
        if preview_url:
            content_parts.append(f'<p><img src="{escape(preview_url, quote=True)}" /></p>')

    if not is_self and target_url:
        safe_url = escape(target_url, quote=True)
        content_parts.append(f'<p><a href="{safe_url}">查看原帖链接</a></p>')

    content_parts.append(f"<p>👍 {score} · 💬 {num_comments}</p>")

    return JSONFeedItem.model_validate(
        {
            "id": post_id,
            "url": permalink_url or target_url,
            "external_url": target_url if target_url != permalink_url else None,
            "title": title,
            "date_published": _format_timestamp(created_utc),
            "content_html": "".join(content_parts),
            "author": {
                "name": f"u/{author}" if author else None,
                "url": f"https://www.reddit.com/user/{author}/" if author else None,
            },
            "tags": [subreddit] if subreddit else None,
        }
    )


def _format_timestamp(value: float) -> str:
    return datetime.fromtimestamp(value, tz=timezone.utc).isoformat()
