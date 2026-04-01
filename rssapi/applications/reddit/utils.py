from datetime import datetime, timezone
from html import escape
from http.cookies import SimpleCookie
from urllib.parse import urljoin

from rdt_cli.auth import Credential
from rdt_cli.client import RedditClient

from rssapi.applications.reddit.types import PostData, SubredditAbout, SubredditListing
from rssapi.applications.rss.schemas.rss.jsonfeed import JSONFeedItem
from rssapi.utils.cache import RandomTTLCache, cached


@cached(RandomTTLCache(4096, 600))
def fetch_subreddit_feed(
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


def _extract_gif(post: PostData) -> dict[str, str] | None:
    """Extract GIF URL from preview variants or media metadata.

    Returns {"type": "video", "url": ...} for mp4 variants,
    or {"type": "image", "url": ...} for animated GIF URLs.
    """
    if post.preview and post.preview.images:
        variants = post.preview.images[0].variants or {}
        mp4 = variants.get("mp4")
        if mp4 and mp4.source and mp4.source.url:
            return {"type": "video", "url": mp4.source.url}
        gif = variants.get("gif")
        if gif and gif.source and gif.source.url:
            return {"type": "image", "url": gif.source.url}

    metadata = post.media_metadata or {}
    for entry in metadata.values():
        if not entry or entry.status != "valid":
            continue
        source = entry.s
        if source and source.gif:
            return {"type": "image", "url": source.gif}
    return None


def _extract_video(post: PostData) -> dict[str, str] | None:
    """Extract video URL from a Reddit-hosted or externally-embedded video post."""
    for media in (post.secure_media, post.media):
        if not media:
            continue
        reddit_video = media.get("reddit_video")
        if reddit_video:
            fallback = reddit_video.get("fallback_url") or ""
            dash = reddit_video.get("dash_url") or ""
            if fallback or dash:
                result: dict[str, str] = {"type": "reddit"}
                if fallback:
                    result["url"] = fallback
                if dash:
                    result["dash_url"] = dash
                return result
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
        if video["type"] == "reddit":
            dash_url = video.get("dash_url")
            fallback_url = video.get("url", "")
            vid_id = f"reddit-video-{post_id}"
            safe_fallback = escape(fallback_url, quote=True) if fallback_url else ""
            title = f"🔊 {title}" if dash_url else f"▶️ {title}"
            # TODO: dash_url 格式的 mpd 需要用 JS 播放，目前大多数 rss 客户端不支持 js 渲染 script 标签, 需要一个代理 API 从 mpd 返回视频流
            if dash_url:
                js_dash = dash_url.replace("\\", "\\\\").replace("'", "\\'")
                src_attr = f' src="{safe_fallback}"' if safe_fallback else ""
                content_parts.append(
                    f'<video id="{vid_id}" controls preload="metadata"{src_attr}></video>'
                    f"<script>"
                    f"(function(){{"
                    f"function i(){{var v=document.getElementById('{vid_id}');"
                    f"var p=dashjs.MediaPlayer().create();"
                    f"p.initialize(v,'{js_dash}',false);}}"
                    f"if(typeof dashjs!=='undefined'){{i()}}else{{"
                    f"var s=document.createElement('script');"
                    f"s.src='https://cdn.dashjs.org/latest/dash.all.min.js';"
                    f"s.onload=i;document.head.appendChild(s);}}"
                    f"}})();"
                    f"</script>"
                )
            else:
                content_parts.append(f'<video controls preload="metadata" src="{safe_fallback}"></video>')
            if permalink_url:
                safe_link = escape(permalink_url, quote=True)
                content_parts.append(f'<p><a href="{safe_link}">🔊 前往 Reddit 播放带声音的视频</a></p>')
        elif video["type"] == "oembed":
            title = f"▶️ {title}"
            content_parts.append(video["html"])

    if is_gallery:
        gallery_urls = _extract_gallery_images(post)
        if gallery_urls:
            title = f"📸 {title}"
            imgs = "".join(f'<img src="{escape(u, quote=True)}" />' for u in gallery_urls)
            content_parts.append(f"<div>{imgs}</div>")
    elif not video:
        gif = _extract_gif(post)
        if gif:
            title = f"🎞️ {title}"
            safe_url = escape(gif["url"], quote=True)
            if gif["type"] == "video":
                content_parts.append(f'<video controls autoplay loop muted src="{safe_url}"></video>')
            else:
                content_parts.append(f'<p><img src="{safe_url}" /></p>')
        else:
            preview_url = _extract_preview_image(post)
            if preview_url:
                title = f"🖼️ {title}"
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
