import asyncio
import contextlib
import html
import logging
import re
import urllib.parse
from collections.abc import Callable, Sequence
from dataclasses import asdict
from functools import lru_cache, wraps
from typing import Any, Iterator

import twitter_cli.auth as twitter_auth
from twitter_cli.client import TwitterClient
from twitter_cli.config import load_config
from twitter_cli.exceptions import TwitterAPIError
from twitter_cli.models import UserProfile

from rssapi.applications.twitter.browser_fallback import (
    TwitterBrowserFallbackError,
    fetch_user_posts_with_browser,
)
from rssapi.applications.twitter.client_transaction import client_transaction_signer
from rssapi.applications.twitter.patch import install_twitter_client_429_no_retry_patch
from rssapi.applications.twitter.types import Tweet
from rssapi.core.settings import settings
from rssapi.utils.md import markdown_parse
from rssapi.utils.sync import async_semaphore

logger = logging.getLogger(__file__)

_twitter_fetch_semaphore = asyncio.Semaphore(settings.twitter.fetch_concurrency)


HTTP_URL_PATTERN = re.compile(r"https?://\S+")
TCO_URL_PATTERN = re.compile(r"https://t\.co/\S+")
install_twitter_client_429_no_retry_patch()


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
        return MyTwitterClient(auth_token, ct0, rate_limit_config, cookie_string=cookie_string)

    raise RuntimeError("auth_token or ct0 is not found in cookies")
    with _mock_twitter_extract_from_browser():
        cookies = twitter_auth.get_cookies()

    return MyTwitterClient(
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


@async_semaphore(_twitter_fetch_semaphore)
async def fetch_feed(max_tweets: int, cookies: str, feed_type: str = "for-you") -> list[Tweet]:
    try:
        return await asyncio.to_thread(_fetch_feed_sync, max_tweets, cookies, feed_type)
    except Exception as e:
        logger.warning(f"failed to fetch twitter feed: {e}")
        raise


@lru_cache(maxsize=1024)
def _fetch_user_profile(screen_name: str, auth_token: str, ct0: str, cookie_string: str | None = None) -> UserProfile:
    client = _build_twitter_client(auth_token, ct0, cookie_string=cookie_string)
    profile = client.fetch_user(screen_name)
    return profile


def _fetch_user_posts_sync(screen_name: str, max_tweets: int, cookies: str) -> list[Tweet]:
    parsed_cookies = _parse_cookie_header(cookies)
    auth_token = parsed_cookies.get("auth_token")
    ct0 = parsed_cookies.get("ct0")
    if not auth_token or not ct0:
        raise RuntimeError("auth_token or ct0 is not found in cookies")

    client = _build_twitter_client(auth_token, ct0, cookie_string=cookies)
    profile = _fetch_user_profile(screen_name, auth_token, ct0, cookies)
    try:
        tweets = client.fetch_user_tweets(profile.id, max_tweets)
    except TwitterAPIError as e:
        if e.status_code != 429 or not settings.twitter.browser_fallback_enabled:
            raise
        logger.warning(f"Twitter UserTweets hit 429, falling back to browser-rendered profile: {screen_name}")
        # The transaction signer keeps a Sync Playwright driver open. Close it before starting the
        # browser fallback because Playwright does not allow nested sync drivers on the same thread.
        client_transaction_signer.close()
        try:
            browser_tweets = fetch_user_posts_with_browser(screen_name, max_tweets, cookies)
        except TwitterBrowserFallbackError as fallback_error:
            logger.error(
                "Twitter UserTweets fallback failed after 429: screen_name=%s kind=%s status=%s",
                screen_name,
                fallback_error.kind,
                fallback_error.status_code,
                exc_info=True,
            )
            raise
        if not browser_tweets:
            empty_fallback_error = TwitterBrowserFallbackError(
                f"Twitter browser fallback returned no posts for {screen_name}",
                kind="no_results",
                status_code=502,
            )
            logger.error(
                "Twitter UserTweets fallback failed after 429: screen_name=%s kind=%s status=%s",
                screen_name,
                empty_fallback_error.kind,
                empty_fallback_error.status_code,
            )
            raise empty_fallback_error
        return browser_tweets

    normalized_screen_name = screen_name.casefold()
    rssapi_tweets = _to_rssapi_tweets(tweets)
    return [
        tweet
        for tweet in rssapi_tweets
        if tweet.is_retweet or tweet.author.screen_name.casefold() == normalized_screen_name
    ]


@async_semaphore(_twitter_fetch_semaphore)
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
        text = markdown_parse(text)
        content_html += f"{text}"

    for m in tweet.media:
        match m.type:
            case "photo" | "animated_gif":
                content_html += f'<img src="{m.url}" width="{m.width}" height="{m.height}" />'
            case "video":
                content_html += (
                    f'<video src="{m.url}" width="{m.width}" height="{m.height}" controls preload="metadata"></video>'
                )

    if tweet.quoted_tweet:
        if tweet.quoted_tweet.article_title and tweet.quoted_tweet.urls:
            content_html += f'<p><a href="{tweet.quoted_tweet.urls[0]}">{tweet.quoted_tweet.article_title}</a></p>'
        else:
            qt = tweet.quoted_tweet
            qt_screen_name = html.escape(qt.author.screen_name)
            qt_name = html.escape(qt.author.name)
            qt_text = markdown_parse(qt.text)
            qt_url = f"https://x.com/{qt_screen_name}/status/{qt.id}"
            content_html += (
                f"<blockquote>"
                f'<p><a href="https://x.com/{qt_screen_name}"><b>{qt_name}</b> @{qt_screen_name}</a></p>'
                f"{qt_text}"
                f'<p><a href="{qt_url}">Original</a></p>'
                f"</blockquote>"
            )

    return content_html


def new_get_instructions(
    original_get_instructions: Callable[[Any], Any],
) -> Callable[[Any], Any]:
    """过滤掉广告推文"""

    filter_components = [
        "for_you_pinned",
        "community_to_join",
        "suggest_who_to_subscribe",
        "suggest_who_to_follow",
        "premium-plus-upsell-prompt",
        "for_you_promoted",
        "following_promoted",
    ]

    @wraps(original_get_instructions)
    def wrapped(data: Any) -> Any:
        instructions = original_get_instructions(data)
        if not isinstance(instructions, list):
            return instructions

        for instruction in instructions:
            entries = instruction.get("entries")

            if entries is not None and isinstance(entries, list):
                component_set = set()
                filtered_entries = []
                for entry in entries:
                    try:
                        component = entry.get("content", {}).get("clientEventInfo", {}).get("component")
                        if component is not None and component in filter_components:
                            logger.debug(f"discard entry: {entry.get('entryId')} - {component}")
                        else:
                            filtered_entries.append(entry)
                            component_set.add(component)
                    except Exception:
                        filtered_entries.append(entry)
                instruction["entries"] = filtered_entries
                logger.debug(f"component_set: {component_set}")
        return instructions

    return wrapped


class MyTwitterClient(TwitterClient):
    def _ensure_client_transaction(self) -> None:
        """Disable twitter-cli's eager ClientTransaction bootstrap.

        twitter-cli 0.8.4 passes a missing ondemand URL to its HTTP client, which
        raises while constructing the native signer. rssapi has an independent
        Playwright signer in ``_build_headers`` and can safely fall back to
        requests without the optional transaction header when it is unavailable.
        """
        self._ct_init_attempted = True

    def _build_headers(self, url="", method="GET"):
        headers = super()._build_headers(url=url, method=method)
        if (
            url
            and settings.twitter.client_transaction_signer_enabled
            and "X-Client-Transaction-Id" not in headers
            and "x-client-transaction-id" not in headers
        ):
            try:
                transaction_id = client_transaction_signer.sign(
                    url,
                    method,
                    settings.twitter.client_transaction_bootstrap_url,
                )
                if transaction_id:
                    headers["X-Client-Transaction-Id"] = transaction_id
                    parsed_url = urllib.parse.urlparse(url)
                    logger.debug(
                        f"Twitter ClientTransaction Playwright signer generated: path={parsed_url.path} "
                        f"method={method} length={len(transaction_id)}"
                    )
            except Exception as e:
                logger.warning(f"Failed to generate Twitter ClientTransaction with Playwright signer: {e}")
        return headers

    def _fetch_timeline(
        self,
        operation_name,
        count,
        get_instructions,
        extra_variables=None,
        override_base_variables=False,
        field_toggles=None,
    ):
        logger.debug(
            f"operation_name: {operation_name}, count: {count}, get_instructions: {get_instructions}, extra_variables: {extra_variables}, override_base_variables: {override_base_variables}, field_toggles: {field_toggles}"
        )
        _get_instructions = new_get_instructions(get_instructions)
        return super()._fetch_timeline(
            operation_name, count, _get_instructions, extra_variables, override_base_variables, field_toggles
        )

    def _api_request(self, url, method="GET", body=None):
        return super()._api_request(url, method, body)
