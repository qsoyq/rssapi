import asyncio
import html
import json
import logging
import os
import re
from collections.abc import Sequence

from typer_utils.utils import is_cmd_exists

from rssapi.applications.twitter.types import Tweet

logger = logging.getLogger(__file__)

HTTP_URL_PATTERN = re.compile(r"https?://\S+")
TCO_URL_PATTERN = re.compile(r"https://t\.co/\S+")


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


async def fetch_feed(max_tweets: int, cookies: str, feed_type: str = "for-you") -> list[Tweet]:
    if not is_cmd_exists("twitter"):
        raise RuntimeError("twitter CLI is not installed")
    environ = os.environ.copy()
    environ["TWITTER_COOKIE"] = cookies
    proc = await asyncio.create_subprocess_exec(
        "twitter",
        "feed",
        "-t",
        feed_type,
        "-n",
        str(max_tweets),
        "--json",
        stdout=asyncio.subprocess.PIPE,
        stderr=asyncio.subprocess.PIPE,
        env=environ,
    )
    stdout, stderr = await proc.communicate()

    if proc.returncode != 0:
        stdout_text = stdout.decode().strip()
        stderr_text = stderr.decode().strip()
        details = []
        if stdout_text:
            details.append(f"stdout={stdout_text}")
        if stderr_text:
            details.append(f"stderr={stderr_text}")

        message = f"twitter CLI failed (code {proc.returncode})"
        if details:
            message = f"{message}: {'; '.join(details)}"

        raise RuntimeError(message)

    output = None
    try:
        output = stdout.decode()
        if "Fetched" in output and "[" in output:
            output = output[output.index("[") :]
        data = json.loads(output)
    except json.JSONDecodeError as e:
        logger.warning(f"failed to parse twitter CLI output: {e}, output: {output}")
        raise

    return [Tweet.model_validate(item) for item in data]


async def fetch_user_posts(screen_name: str, max_tweets: int) -> list[Tweet]:
    if not is_cmd_exists("twitter"):
        raise RuntimeError("twitter CLI is not installed")
    proc = await asyncio.create_subprocess_exec(
        "twitter",
        "user-posts",
        screen_name,
        "-n",
        str(max_tweets),
        "--json",
        stdout=asyncio.subprocess.PIPE,
        stderr=asyncio.subprocess.PIPE,
    )
    stdout, stderr = await proc.communicate()

    if proc.returncode != 0:
        stdout_text = stdout.decode().strip()
        stderr_text = stderr.decode().strip()
        details = []
        if stdout_text:
            details.append(f"stdout={stdout_text}")
        if stderr_text:
            details.append(f"stderr={stderr_text}")

        message = f"twitter CLI failed (code {proc.returncode})"
        if details:
            message = f"{message}: {'; '.join(details)}"

        raise RuntimeError(message)

    output = None
    try:
        output = stdout.decode()
        if "Fetched" in output and "[" in output:
            output = output[output.index("[") :]
        data = json.loads(output)
    except json.JSONDecodeError as e:
        logger.warning(f"failed to parse twitter CLI output: {e}, output: {output}")
        raise e

    return [Tweet.model_validate(item) for item in data]


def content_html_from_tweet(tweet: Tweet) -> str:
    content_html = ""
    if tweet.text:
        text = text_without_tco_links(tweet.text)
        content_html = f"<p>{html.escape(text)}</p>"

    for m in tweet.media:
        match m.type:
            case "photo" | "animated_gif":
                content_html += f'<img src="{m.url}" width="{m.width}" height="{m.height}" />'
            case "video":
                content_html += (
                    f'<video src="{m.url}" width="{m.width}" height="{m.height}" controls preload="metadata"></video>'
                )
    return content_html
