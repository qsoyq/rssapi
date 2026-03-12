import asyncio
import contextlib
import html
import logging
import re
from collections.abc import Sequence
from dataclasses import asdict
from typing import Any, Iterator

import twitter_cli.auth as twitter_auth
from twitter_cli.client import TwitterClient
from twitter_cli.config import load_config

from rssapi.applications.twitter.types import Tweet

logger = logging.getLogger(__file__)

HTTP_URL_PATTERN = re.compile(r"https?://\S+")
TCO_URL_PATTERN = re.compile(r"https://t\.co/\S+")
# install_twitter_client_429_no_retry_patch()


class AuthorScreenNameMapping:
    _mapping: dict[str, str] = {}

    @classmethod
    def set(cls, author_name: str, screen_name: str) -> None:
        cls._mapping[author_name] = screen_name

    @classmethod
    def get(cls, author_name: str) -> str | None:
        return cls._mapping.get(author_name)


def title_from_text_by_delimiter_priority(text: str, truncation_chars: Sequence[str] | None = None) -> str:
    """Truncate text using the first matching delimiter in priority order."""
    if truncation_chars is None:
        truncation_chars = ("\n", "?", "!", ".", "。")

    cutoff = len(text)
    for char in truncation_chars:
        index = text.find(char)
        if index != -1:
            cutoff = min(cutoff, index)
            break
    return text[:cutoff]


def _normalize_text_whitespace(text: str) -> str:
    text = re.sub(r"[ \t]{2,}", " ", text)
    text = re.sub(r"[ \t]+\n", "\n", text)
    text = re.sub(r"\n[ \t]+", "\n", text)
    return text.strip()


def text_without_http_links(text: str) -> str:
    """Remove all http/https links from text while keeping surrounding text readable."""
    text = HTTP_URL_PATTERN.sub("", text)
    return _normalize_text_whitespace(text)


def text_without_tco_links(text: str) -> str:
    """Remove all https://t.co links from text while keeping surrounding text readable."""
    text = TCO_URL_PATTERN.sub("", text)
    return _normalize_text_whitespace(text)


def title_emoji_prefix_from_tweet(tweet: Tweet) -> str:
    """Generate a prefix for the tweet media (photo, video, animated gif) and retweet indicator."""
    media_photo = False
    media_video = False
    is_retweet = tweet.is_retweet

    for m in tweet.media:
        match m.type:
            case "photo" | "animated_gif":
                media_photo = True
            case "video":
                media_video = True

    prefix_parts = []
    if media_video:
        prefix_parts.append("▶️")
    if media_photo:
        prefix_parts.append("📸")
    if is_retweet:
        prefix_parts.append("🔁")
    if tweet.quoted_tweet:
        prefix_parts.append("💬")
    return " ".join(prefix_parts)


def _parse_cookie_header(cookies: str) -> dict[str, str]:
    parsed_cookies: dict[str, str] = {}
    for cookie in cookies.split(";"):
        chunk = cookie.strip()
        if not chunk:
            continue

        name, sep, value = chunk.partition("=")
        if not sep:
            continue

        parsed_cookies[name.strip()] = value.strip()
    return parsed_cookies


@contextlib.contextmanager
def _mock_twitter_extract_from_browser() -> Iterator[None]:
    original_extract_from_browser = twitter_auth.extract_from_browser

    def _raise_browser_fallback_disabled() -> None:
        raise RuntimeError("twitter_cli extract_from_browser is disabled")

    twitter_auth.extract_from_browser = _raise_browser_fallback_disabled
    try:
        yield
    finally:
        twitter_auth.extract_from_browser = original_extract_from_browser


def _build_twitter_client(
    auth_token: str | None = None,
    ct0: str | None = None,
    cookie_string: str | None = None,
) -> TwitterClient:
    rate_limit_config = load_config().get("rateLimit")
    if auth_token and ct0:
        return TwitterClient(auth_token, ct0, rate_limit_config, cookie_string=cookie_string)

    with _mock_twitter_extract_from_browser():
        cookies = twitter_auth.get_cookies()

    return TwitterClient(
        cookies["auth_token"],
        cookies["ct0"],
        rate_limit_config,
        cookie_string=cookies.get("cookie_string"),
    )


def _to_rssapi_tweets(tweets: list[Any]) -> list[Tweet]:
    return [Tweet.model_validate(asdict(tweet)) for tweet in tweets]


def _fetch_feed_sync(max_tweets: int, cookies: str, feed_type: str) -> list[Tweet]:
    parsed_cookies = _parse_cookie_header(cookies)
    auth_token = parsed_cookies.get("auth_token")
    ct0 = parsed_cookies.get("ct0")
    if not auth_token or not ct0:
        raise RuntimeError("auth_token or ct0 is not found in cookies")

    client = _build_twitter_client(auth_token, ct0, cookie_string=cookies)
    if feed_type == "following":
        tweets = client.fetch_following_feed(max_tweets)
    else:
        tweets = client.fetch_home_timeline(max_tweets)
    return _to_rssapi_tweets(tweets)


async def fetch_feed(max_tweets: int, cookies: str, feed_type: str = "for-you") -> list[Tweet]:
    try:
        return await asyncio.to_thread(_fetch_feed_sync, max_tweets, cookies, feed_type)
    except Exception as e:
        logger.warning(f"failed to fetch twitter feed: {e}")
        raise


def _fetch_user_posts_sync(screen_name: str, max_tweets: int, cookies: str) -> list[Tweet]:
    parsed_cookies = _parse_cookie_header(cookies)
    auth_token = parsed_cookies.get("auth_token")
    ct0 = parsed_cookies.get("ct0")
    if not auth_token or not ct0:
        raise RuntimeError("auth_token or ct0 is not found in cookies")

    client = _build_twitter_client(auth_token, ct0, cookie_string=cookies)
    profile = client.fetch_user(screen_name)
    tweets = client.fetch_user_tweets(profile.id, max_tweets)
    normalized_screen_name = screen_name.casefold()
    rssapi_tweets = _to_rssapi_tweets(tweets)
    return [
        tweet
        for tweet in rssapi_tweets
        if tweet.is_retweet or tweet.author.screen_name.casefold() == normalized_screen_name
    ]


async def fetch_user_posts(screen_name: str, max_tweets: int, cookies: str) -> list[Tweet]:
    try:
        return await asyncio.to_thread(_fetch_user_posts_sync, screen_name, max_tweets, cookies)
    except Exception as e:
        logger.warning(f"failed to fetch twitter user posts: {e}")
        raise


def content_html_from_tweet(tweet: Tweet) -> str:
    content_html = ""

    if tweet.is_retweet and tweet.retweeted_by:
        rt_name = html.escape(tweet.retweeted_by)
        content_html += f'<p>🔁 RT by <a href="https://x.com/{rt_name}">@{rt_name}</a></p>'

    if tweet.text:
        text = text_without_tco_links(tweet.text)
        content_html += f"<p>{html.escape(text)}</p>"

    for m in tweet.media:
        match m.type:
            case "photo" | "animated_gif":
                content_html += f'<img src="{m.url}" width="{m.width}" height="{m.height}" />'
            case "video":
                content_html += (
                    f'<video src="{m.url}" width="{m.width}" height="{m.height}" controls preload="metadata"></video>'
                )

    if tweet.quoted_tweet:
        qt = tweet.quoted_tweet
        qt_screen_name = html.escape(qt.author.screen_name)
        qt_name = html.escape(qt.author.name)
        qt_text = html.escape(text_without_tco_links(qt.text))
        qt_url = f"https://x.com/{qt_screen_name}/status/{qt.id}"
        content_html += (
            f"<blockquote>"
            f'<p><a href="https://x.com/{qt_screen_name}"><b>{qt_name}</b> @{qt_screen_name}</a></p>'
            f"<p>{qt_text}</p>"
            f'<p><a href="{qt_url}">Original</a></p>'
            f"</blockquote>"
        )

    return content_html
