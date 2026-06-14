import hashlib
import html
import time
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, TypedDict, cast
from urllib.parse import urlencode

from curl_cffi import requests
from fastapi import HTTPException

from rssapi.applications.rss.schemas.rss.jsonfeed import JSONFeedAuthor, JSONFeedItem

BILIBILI_API_BASE = "https://api.bilibili.com"
BILIBILI_SPACE_BASE = "https://space.bilibili.com"
BILIBILI_FAVICON = "https://www.bilibili.com/favicon.ico"

BILIBILI_HEADERS = {
    "User-Agent": (
        "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) "
        "AppleWebKit/537.36 (KHTML, like Gecko) "
        "Chrome/120.0.0.0 Safari/537.36"
    ),
    "Referer": "https://www.bilibili.com/",
    "Accept": "application/json, text/plain, */*",
    "Accept-Language": "zh-CN,zh;q=0.9,en;q=0.8",
}

MIXIN_KEY_ENC_TAB = [
    46,
    47,
    18,
    2,
    53,
    8,
    23,
    32,
    15,
    50,
    10,
    31,
    58,
    3,
    45,
    35,
    27,
    43,
    5,
    49,
    33,
    9,
    42,
    19,
    29,
    28,
    14,
    39,
    12,
    38,
    41,
    13,
    37,
    48,
    7,
    16,
    24,
    55,
    40,
    61,
    26,
    17,
    0,
    1,
    60,
    51,
    30,
    4,
    22,
    25,
    54,
    21,
    56,
    59,
    6,
    63,
    57,
    62,
    11,
    36,
    20,
    34,
    44,
    52,
]


class BilibiliUserInfo(TypedDict, total=False):
    mid: str
    name: str
    face: str
    sign: str


def normalize_url(url: str | None) -> str | None:
    if not url:
        return None
    if url.startswith("//"):
        return f"https:{url}"
    if url.startswith("http://"):
        return f"https://{url.removeprefix('http://')}"
    return url


def timestamp_to_iso(timestamp: int | str | None) -> str | None:
    if timestamp is None or timestamp == "":
        return None
    return datetime.fromtimestamp(int(timestamp), tz=timezone.utc).isoformat()


def _extract_wbi_key(url: str) -> str:
    return Path(url).stem


def _get_mixin_key(img_key: str, sub_key: str) -> str:
    raw = img_key + sub_key
    return "".join(raw[i] for i in MIXIN_KEY_ENC_TAB)[:32]


def sign_wbi_params(params: dict[str, Any], img_key: str, sub_key: str) -> dict[str, Any]:
    signed = {**params, "wts": int(time.time())}
    mixin_key = _get_mixin_key(img_key, sub_key)
    filtered = {key: "".join(ch for ch in str(value) if ch not in "!'()*") for key, value in signed.items()}
    query = urlencode(sorted(filtered.items()))
    signed["w_rid"] = hashlib.md5(f"{query}{mixin_key}".encode()).hexdigest()
    return signed


def _raise_for_bilibili_error(payload: dict[str, Any], upstream: str) -> None:
    code = payload.get("code")
    if code == 0:
        return
    message = payload.get("message", "unknown upstream error")
    if code == -799:
        raise HTTPException(
            status_code=429,
            detail=f"fetch bilibili {upstream} error: {message} (code: {code})",
        )
    raise HTTPException(status_code=502, detail=f"fetch bilibili {upstream} error: {message} (code: {code})")


def _raise_for_bilibili_http_error(resp, upstream: str) -> None:
    if resp.status_code < 400:
        return
    if resp.status_code == 412:
        raise HTTPException(
            status_code=429,
            detail=(
                f"fetch bilibili {upstream} error: request rejected by bilibili security control policy (HTTP 412)"
            ),
        )
    raise HTTPException(status_code=resp.status_code, detail=resp.text)


async def fetch_user_info(client: requests.Session, mid: int) -> BilibiliUserInfo | None:
    resp = client.get(f"{BILIBILI_API_BASE}/x/web-interface/card", params={"mid": mid})
    _raise_for_bilibili_http_error(resp, "user info")
    payload = resp.json()
    if payload.get("code") != 0:
        return None
    card = (payload.get("data") or {}).get("card") or {}
    return {
        "mid": str(card.get("mid") or mid),
        "name": card.get("name") or str(mid),
        "face": normalize_url(card.get("face")) or "",
        "sign": card.get("sign") or "",
    }


def format_duration(duration: int | str | None) -> str | None:
    if duration is None or duration == "":
        return None
    if isinstance(duration, str) and ":" in duration:
        return duration
    seconds = int(duration)
    minutes, second = divmod(seconds, 60)
    hour, minute = divmod(minutes, 60)
    if hour:
        return f"{hour}:{minute:02d}:{second:02d}"
    return f"{minute}:{second:02d}"


def _season_archive_to_video(archive: dict[str, Any]) -> dict[str, Any]:
    stat = archive.get("stat") or {}
    return {
        "aid": archive.get("aid"),
        "bvid": archive.get("bvid"),
        "title": archive.get("title"),
        "description": archive.get("desc") or "",
        "pic": archive.get("pic"),
        "created": archive.get("pubdate") or archive.get("ctime"),
        "length": archive.get("duration"),
        "play": stat.get("view"),
        "video_review": stat.get("danmaku"),
        "comment": stat.get("reply"),
    }


def _extract_archives_from_seasons(seasons: list[dict[str, Any]], page_size: int) -> list[dict[str, Any]]:
    archives = []
    for season in seasons:
        archives.extend(cast(list[dict[str, Any]], season.get("archives") or []))
    archives.sort(key=lambda archive: archive.get("pubdate") or archive.get("ctime") or 0, reverse=True)
    return [_season_archive_to_video(archive) for archive in archives[:page_size]]


async def fetch_user_videos(client: requests.Session, mid: int, page_size: int) -> list[dict[str, Any]]:
    resp = client.get(
        f"{BILIBILI_API_BASE}/x/polymer/web-space/seasons_series_list",
        params={"mid": mid, "page_num": 1, "page_size": 20},
    )
    _raise_for_bilibili_http_error(resp, "user video collections")
    payload = resp.json()
    _raise_for_bilibili_error(payload, "user video collections")
    items_lists = (payload.get("data") or {}).get("items_lists") or {}
    videos = _extract_archives_from_seasons(
        cast(list[dict[str, Any]], items_lists.get("seasons_list") or []), page_size
    )
    if len(videos) >= page_size:
        return videos

    resp = client.get(
        f"{BILIBILI_API_BASE}/x/polymer/web-space/home/seasons_series",
        params={"mid": mid, "page_num": 1, "page_size": 20},
    )
    _raise_for_bilibili_http_error(resp, "user home video collections")
    payload = resp.json()
    _raise_for_bilibili_error(payload, "user home video collections")
    items_lists = (payload.get("data") or {}).get("items_lists") or {}
    videos.extend(
        _extract_archives_from_seasons(cast(list[dict[str, Any]], items_lists.get("seasons_list") or []), page_size)
    )
    deduped = {video.get("bvid") or video.get("aid"): video for video in videos}
    return sorted(deduped.values(), key=lambda video: video.get("created") or 0, reverse=True)[:page_size]


def video_to_jsonfeed_item(video: dict[str, Any], author: JSONFeedAuthor) -> JSONFeedItem:
    bvid = video.get("bvid") or f"av{video.get('aid')}"
    video_url = f"https://www.bilibili.com/video/{bvid}"
    cover = normalize_url(video.get("pic"))
    description = html.escape(video.get("description") or "")
    title = html.escape(video.get("title") or bvid)
    stats = [
        ("播放", video.get("play")),
        ("弹幕", video.get("video_review")),
        ("评论", video.get("comment")),
        ("时长", format_duration(video.get("length"))),
    ]
    stats_html = "".join(
        f"<li>{name}: {html.escape(str(value))}</li>" for name, value in stats if value not in (None, "")
    )
    image_html = f'<p><img src="{html.escape(cover)}" alt="{title}" /></p>' if cover else ""
    content_html = (
        f'{image_html}<p>{description}</p><ul>{stats_html}</ul><p><a href="{video_url}">在 Bilibili 查看</a></p>'
    )

    return JSONFeedItem.model_validate(
        {
            "id": f"bilibili-video-{bvid}",
            "url": video_url,
            "title": video.get("title") or bvid,
            "content_html": content_html,
            "summary": video.get("description") or None,
            "image": cover,
            "date_published": timestamp_to_iso(video.get("created")),
            "author": author,
        }
    )


async def fetch_user_feed_data(mid: int, page_size: int) -> tuple[BilibiliUserInfo | None, list[JSONFeedItem]]:
    headers = {**BILIBILI_HEADERS, "Referer": f"{BILIBILI_SPACE_BASE}/{mid}/video"}
    with requests.Session(headers=headers, timeout=30, impersonate="chrome136") as client:
        user = await fetch_user_info(client, mid)
        author = JSONFeedAuthor.model_validate(
            {
                "name": (user or {}).get("name") or str(mid),
                "url": f"{BILIBILI_SPACE_BASE}/{mid}",
                "avatar": (user or {}).get("face") or None,
            }
        )
        videos = await fetch_user_videos(client, mid, page_size)
        return user, [video_to_jsonfeed_item(video, author) for video in videos]
