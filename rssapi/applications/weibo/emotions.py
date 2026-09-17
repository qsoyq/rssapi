import json
import re
from collections.abc import Mapping
from functools import lru_cache
from html import escape
from importlib.resources import files
from typing import Any

from bs4 import BeautifulSoup, Tag

_EMOTION_PATTERN = re.compile(r"\[[^\[\]\n]{1,32}\]")
_EMOTION_DATA_RESOURCE = "emotions.json"


@lru_cache(maxsize=1)
def bundled_emotion_map() -> dict[str, str]:
    raw = files("rssapi.applications.weibo").joinpath(_EMOTION_DATA_RESOURCE).read_text(encoding="utf-8")
    payload = json.loads(raw)
    if not isinstance(payload, dict):
        return {}
    return {str(phrase): str(url) for phrase, url in payload.items() if phrase and url}


def emotion_img_html(phrase: str, url: str) -> str:
    return (
        f'<img class="weibo-emoji" alt="{escape(phrase, quote=True)}" '
        f'src="{escape(url, quote=True)}" width="20" height="20" />'
    )


def replace_emotions(escaped_text: str, mapping: Mapping[str, str]) -> str:
    if "[" not in escaped_text or not mapping:
        return escaped_text

    def replacer(match: re.Match[str]) -> str:
        phrase = match.group(0)
        url = mapping.get(phrase)
        if not url:
            return phrase
        return emotion_img_html(phrase, url)

    return _EMOTION_PATTERN.sub(replacer, escaped_text)


def render_emotion_text(text: str, mapping: Mapping[str, str] | None = None) -> str:
    escaped = escape(text).replace("\n", "<br>")
    return replace_emotions(escaped, mapping if mapping is not None else bundled_emotion_map())


def emotion_map_from_html(value: Any) -> dict[str, str]:
    if not isinstance(value, str) or "<img" not in value.lower():
        return {}

    soup = BeautifulSoup(value, "html.parser")
    mapping: dict[str, str] = {}
    for image in soup.find_all("img"):
        if not isinstance(image, Tag):
            continue
        alt = image.get("alt")
        url = _safe_image_url(image.get("src"))
        if isinstance(alt, str) and alt.startswith("[") and alt.endswith("]") and url:
            mapping[alt] = url
    return mapping


def emotion_map_for_post(post: dict[str, Any]) -> dict[str, str]:
    mapping = dict(bundled_emotion_map())
    mapping.update(emotion_map_from_html(post.get("text")))
    retweeted_status = post.get("retweeted_status")
    if isinstance(retweeted_status, dict):
        mapping.update(emotion_map_from_html(retweeted_status.get("text")))
    return mapping


def _safe_image_url(value: Any) -> str | None:
    if not isinstance(value, str):
        return None
    url = value.strip()
    if not url.startswith(("http://", "https://")) or any(character.isspace() for character in url):
        return None
    lowered = url.lower()
    if lowered.startswith("javascript:") or lowered.startswith("data:"):
        return None
    if url.startswith("http://"):
        return f"https://{url[len('http://') :]}"
    return url
