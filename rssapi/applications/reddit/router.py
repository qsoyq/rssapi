# https://www.reddit.com/r/programming

from datetime import datetime, timezone
from html import escape
from http.cookies import SimpleCookie
from typing import Any

from fastapi import APIRouter, Header, HTTPException, Path, Query, Request
from fastapi.concurrency import run_in_threadpool
from rdt_cli.auth import Credential
from rdt_cli.client import RedditClient
from rdt_cli.exceptions import RedditApiError
from rdt_cli.models import SubredditInfo
from rdt_cli.parser import parse_subreddit_info

from rssapi.applications.rss.schemas.rss.jsonfeed import JSONFeed, JSONFeedItem
from rssapi.core.circuit_breaker import circuit_breaker
from rssapi.core.responses import PrettyJSONFeedResponse

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
        "description": about.public_description or about.description or "",
        "home_page_url": f"https://www.reddit.com/r/{subreddit}/",
        "feed_url": str(req.url),
        "icon": "https://www.reddit.com/favicon.ico",
        "favicon": "https://www.reddit.com/favicon.ico",
        "items": items,
    }
    return feed


def _fetch_subreddit_feed(
    subreddit: str, max_posts: int, cookies: str | None
) -> tuple[SubredditInfo, list[JSONFeedItem]]:
    credential = _build_credential(cookies)
    with RedditClient(credential) as client:
        about = parse_subreddit_info(client.get_subreddit_about(subreddit))
        raw_listing = client.get_subreddit(subreddit, limit=max_posts)
    children = raw_listing.get("data", {}).get("children", [])
    items = [_build_feed_item(child.get("data", child)) for child in children]
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


def _extract_gallery_images(data: dict[str, Any]) -> list[str]:
    """Extract image URLs from a gallery post's media_metadata, ordered by gallery_data."""
    metadata = data.get("media_metadata") or {}
    gallery_items = (data.get("gallery_data") or {}).get("items") or []

    ordered_ids = [item["media_id"] for item in gallery_items if "media_id" in item]
    if not ordered_ids:
        ordered_ids = list(metadata.keys())

    urls: list[str] = []
    for media_id in ordered_ids:
        entry = metadata.get(media_id, {})
        if entry.get("status") != "valid":
            continue
        source = entry.get("s", {})
        url = source.get("u") or source.get("gif") or ""
        if url:
            urls.append(url)
    return urls


def _extract_preview_image(data: dict[str, Any]) -> str | None:
    """Extract the best-quality preview image URL from a post."""
    preview = data.get("preview") or {}
    images = preview.get("images") or []
    if not images:
        return None
    source = images[0].get("source", {})
    return source.get("url") or None


def _build_feed_item(data: dict[str, Any]) -> JSONFeedItem:
    post_id = str(data.get("id", ""))
    title = str(data.get("title", ""))
    permalink = str(data.get("permalink", ""))
    url = str(data.get("url", ""))
    selftext_html = data.get("selftext_html") or ""
    selftext = str(data.get("selftext", ""))
    is_self = bool(data.get("is_self", True))
    is_gallery = bool(data.get("is_gallery", False))
    score = int(data.get("score", 0) or 0)
    num_comments = int(data.get("num_comments", 0) or 0)
    author = str(data.get("author", ""))
    subreddit = str(data.get("subreddit", ""))
    created_utc = float(data.get("created_utc", 0) or 0)

    permalink_url = f"https://www.reddit.com{permalink}" if permalink else None
    target_url = url or permalink_url

    content_parts: list[str] = []

    if selftext_html:
        content_parts.append(selftext_html)
    elif selftext:
        content_parts.append(f"<p>{escape(selftext).replace(chr(10), '<br>')}</p>")

    if is_gallery:
        gallery_urls = _extract_gallery_images(data)
        if gallery_urls:
            imgs = "".join(f'<img src="{escape(u, quote=True)}" />' for u in gallery_urls)
            content_parts.append(f"<div>{imgs}</div>")
    else:
        preview_url = _extract_preview_image(data)
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
