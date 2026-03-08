import asyncio
import html
import json
import logging
from collections.abc import Sequence

from typer_utils.utils import is_cmd_exists

from rssapi.applications.twitter.types import Tweet

logger = logging.getLogger(__file__)


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
        truncation_chars = ("\n", ".", "。")
    cutoff = len(text)
    for char in truncation_chars:
        index = text.find(char)
        if index != -1:
            cutoff = min(cutoff, index)
            break
    return text[:cutoff]


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
        raise RuntimeError(f"twitter CLI failed (code {proc.returncode}): {stderr.decode().strip()}")

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
        content_html = f"<p>{html.escape(tweet.text)}</p>"
    for m in tweet.media:
        match m.type:
            case "photo" | "animated_gif":
                content_html += f'<img src="{m.url}" width="{m.width}" height="{m.height}" />'
            case "video":
                content_html += (
                    f'<video src="{m.url}" width="{m.width}" height="{m.height}" controls preload="metadata"></video>'
                )
    return content_html
