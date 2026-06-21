import hashlib
import html
import logging
import time
from collections.abc import Awaitable, Callable
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, TypedDict, cast
from urllib.parse import urlencode

from curl_cffi import requests
from fastapi import HTTPException

from rssapi.applications.rss.schemas.rss.jsonfeed import JSONFeedAuthor, JSONFeedItem

logger = logging.getLogger(__name__)

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


async def _get_wbi_keys(client: requests.Session) -> tuple[str, str]:
    resp = client.get(f"{BILIBILI_API_BASE}/x/web-interface/nav")
    _raise_for_bilibili_http_error(resp, "wbi keys")
    # nav 在未登录时返回 code -101，但仍带 wbi_img，故不对 code 报错
    wbi_img = ((resp.json().get("data") or {}).get("wbi_img")) or {}
    img_key = _extract_wbi_key(wbi_img.get("img_url") or "")
    sub_key = _extract_wbi_key(wbi_img.get("sub_url") or "")
    if not img_key or not sub_key:
        raise HTTPException(status_code=502, detail="fetch bilibili wbi keys error: missing img/sub key")
    return img_key, sub_key


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


# 静态最小值，降低 -352 风控概率；无需真实采集设备指纹
_DM_IMG_STR = "V2ViR0wgMS4wIChPcGVuR0wgRVMgMi4wIENocm9taXVtKQ"
_DM_COVER_IMG_STR = "QU5HTEUgKEFwcGxlLCBBcHBsZSBNMSBQcm8sIE9wZW5HTCA0LjEpR29vZ2xlIEluYy4gKEFwcGxlKQ"
_DM_IMG_INTER = '{"ds":[],"wh":[0,0,0],"of":[0,0,0]}'


async def fetch_user_submissions(client: requests.Session, mid: int, page_size: int) -> list[dict[str, Any]]:
    """通过 WBI 签名的 /x/space/wbi/arc/search 拉取用户完整投稿列表。"""
    img_key, sub_key = await _get_wbi_keys(client)
    params = sign_wbi_params(
        {
            "mid": mid,
            "ps": page_size,
            "pn": 1,
            "order": "pubdate",
            "platform": "web",
            "web_location": 1550101,
            "dm_img_list": "[]",
            "dm_img_str": _DM_IMG_STR,
            "dm_cover_img_str": _DM_COVER_IMG_STR,
            "dm_img_inter": _DM_IMG_INTER,
        },
        img_key,
        sub_key,
    )
    resp = client.get(f"{BILIBILI_API_BASE}/x/space/wbi/arc/search", params=params)
    _raise_for_bilibili_http_error(resp, "user submissions")
    payload = resp.json()
    _raise_for_bilibili_error(payload, "user submissions")
    vlist = (((payload.get("data") or {}).get("list") or {}).get("vlist")) or []
    return cast(list[dict[str, Any]], vlist)[:page_size]


def _video_identifier_params(video: dict[str, Any]) -> dict[str, Any]:
    bvid = video.get("bvid")
    if bvid:
        return {"bvid": bvid}
    aid = video.get("aid")
    if aid:
        return {"avid": aid}
    return {}


def _video_debug_id(video: dict[str, Any]) -> str:
    return str(video.get("bvid") or video.get("aid") or "unknown")


def _extract_video_cid(video: dict[str, Any], view_data: dict[str, Any] | None = None) -> int | str | None:
    cid = video.get("cid")
    if cid not in (None, ""):
        return cast(int | str, cid)

    if not view_data:
        return None

    cid = view_data.get("cid")
    if cid not in (None, ""):
        return cast(int | str, cid)

    pages = view_data.get("pages") or []
    if not pages:
        return None
    first_page = pages[0] or {}
    cid = first_page.get("cid")
    if cid in (None, ""):
        return None
    return cast(int | str, cid)


def _extract_playable_url_from_playurl_data(playurl_data: dict[str, Any]) -> str | None:
    for entry in playurl_data.get("durl") or []:
        url = normalize_url(entry.get("url"))
        if url:
            return url
        for backup_url in entry.get("backup_url") or []:
            url = normalize_url(backup_url)
            if url:
                return url
    return None


async def fetch_playable_video_url(client: requests.Session, video: dict[str, Any]) -> str | None:
    video_id = _video_debug_id(video)
    playable_url = normalize_url(video.get("playable_url") or video.get("video_url") or video.get("src"))
    if playable_url:
        logger.info(f"bilibili playable url already present: video={video_id}")
        return playable_url

    identifier_params = _video_identifier_params(video)
    if not identifier_params:
        logger.warning(f"bilibili playable url skipped: video={video_id} missing bvid/aid")
        return None

    cid = _extract_video_cid(video)
    if cid is None:
        resp = client.get(f"{BILIBILI_API_BASE}/x/web-interface/view", params=identifier_params)
        _raise_for_bilibili_http_error(resp, "video view")
        payload = resp.json()
        if payload.get("code") != 0:
            logger.warning(
                f"bilibili video view failed: video={video_id} code={payload.get('code')} "
                f"message={payload.get('message')}"
            )
        _raise_for_bilibili_error(payload, "video view")
        cid = _extract_video_cid(video, payload.get("data") or {})
    if cid is None:
        logger.warning(f"bilibili playable url skipped: video={video_id} missing cid")
        return None

    img_key, sub_key = await _get_wbi_keys(client)
    params = sign_wbi_params(
        {
            **identifier_params,
            "cid": cid,
            "qn": 80,
            "fnval": 4048,
            "fnver": 0,
            "fourk": 0,
            "otype": "json",
            "try_look": 1,
        },
        img_key,
        sub_key,
    )
    resp = client.get(
        f"{BILIBILI_API_BASE}/x/player/wbi/playurl",
        params=params,
    )
    _raise_for_bilibili_http_error(resp, "video playurl")
    payload = resp.json()
    if payload.get("code") != 0:
        logger.warning(
            f"bilibili video playurl failed: video={video_id} cid={cid} code={payload.get('code')} "
            f"message={payload.get('message')}"
        )
    _raise_for_bilibili_error(payload, "video playurl")
    playurl_data = payload.get("data") or payload.get("result") or {}
    playable_url = _extract_playable_url_from_playurl_data(playurl_data)
    if playable_url:
        logger.info(f"bilibili playable url resolved: video={video_id} cid={cid}")
        return playable_url

    dash = playurl_data.get("dash") or {}
    logger.warning(
        f"bilibili wbi playurl missing durl: video={video_id} cid={cid} "
        f"durl_count={len(playurl_data.get('durl') or [])} "
        f"dash_video_count={len(dash.get('video') or [])} dash_audio_count={len(dash.get('audio') or [])}"
    )

    resp = client.get(
        f"{BILIBILI_API_BASE}/x/player/playurl",
        params={
            **identifier_params,
            "cid": cid,
            "qn": 80,
            "fnval": 0,
            "fnver": 0,
            "fourk": 0,
            "platform": "html5",
            "high_quality": 1,
            "otype": "json",
        },
    )
    _raise_for_bilibili_http_error(resp, "html5 video playurl")
    payload = resp.json()
    if payload.get("code") != 0:
        logger.warning(
            f"bilibili html5 video playurl failed: video={video_id} cid={cid} code={payload.get('code')} "
            f"message={payload.get('message')}"
        )
    _raise_for_bilibili_error(payload, "html5 video playurl")
    playurl_data = payload.get("data") or payload.get("result") or {}
    playable_url = _extract_playable_url_from_playurl_data(playurl_data)
    if playable_url:
        logger.info(f"bilibili html5 playable url resolved: video={video_id} cid={cid}")
        return playable_url

    dash = playurl_data.get("dash") or {}
    logger.warning(
        f"bilibili html5 playable url missing durl: video={video_id} cid={cid} "
        f"durl_count={len(playurl_data.get('durl') or [])} "
        f"dash_video_count={len(dash.get('video') or [])} dash_audio_count={len(dash.get('audio') or [])}"
    )
    return None


async def _attach_playable_video_urls(
    client: requests.Session,
    videos: list[dict[str, Any]],
    fetch_playable_url: Callable[[requests.Session, dict[str, Any]], Awaitable[str | None]],
) -> list[dict[str, Any]]:
    enriched = []
    for video in videos:
        item = {**video}
        try:
            playable_url = await fetch_playable_url(client, item)
        except HTTPException as exc:
            logger.warning(
                f"bilibili playable url fallback: video={_video_debug_id(item)} "
                f"status_code={exc.status_code} detail={exc.detail}"
            )
            playable_url = None
        except requests.RequestsError as exc:
            logger.warning(f"bilibili playable url fallback: video={_video_debug_id(item)} error={exc}")
            playable_url = None
        if playable_url:
            item["playable_url"] = playable_url
        else:
            logger.warning(f"bilibili feed item uses image fallback: video={_video_debug_id(item)}")
        enriched.append(item)
    return enriched


def _build_video_media_html(playable_url: str | None, cover: str | None, title: str) -> str:
    if playable_url:
        attrs = [
            "controls",
            'preload="metadata"',
            f'src="{html.escape(playable_url, quote=True)}"',
        ]
        if cover:
            attrs.append(f'poster="{html.escape(cover, quote=True)}"')
        return f"<p><video {' '.join(attrs)}>{title}</video></p>"
    if cover:
        return f'<p><img src="{html.escape(cover, quote=True)}" alt="{title}" /></p>'
    return ""


def _build_video_direct_link_html(playable_url: str | None, video_url: str) -> str:
    if not playable_url:
        return ""
    safe_url = html.escape(playable_url, quote=True)
    safe_referer = html.escape(video_url, quote=True)
    return (
        f'<p><a href="{safe_url}" rel="noopener noreferrer">视频 CDN 直链（无需 cookies，需要 Bilibili Referer）</a></p>'
        f"<p>播放请求 Referer: <code>{safe_referer}</code></p>"
    )


def video_to_jsonfeed_item(video: dict[str, Any], author: JSONFeedAuthor) -> JSONFeedItem:
    bvid = video.get("bvid") or f"av{video.get('aid')}"
    video_url = f"https://www.bilibili.com/video/{bvid}"
    cover = normalize_url(video.get("pic"))
    description = html.escape(video.get("description") or "")
    title = html.escape(video.get("title") or bvid)
    playable_url = normalize_url(video.get("playable_url"))
    stats = [
        ("播放", video.get("play")),
        ("弹幕", video.get("video_review")),
        ("评论", video.get("comment")),
        ("时长", format_duration(video.get("length"))),
    ]
    stats_html = "".join(
        f"<li>{name}: {html.escape(str(value))}</li>" for name, value in stats if value not in (None, "")
    )
    media_html = _build_video_media_html(playable_url, cover, title)
    direct_link_html = _build_video_direct_link_html(playable_url, video_url)
    content_html = (
        f"{media_html}<p>{description}</p><ul>{stats_html}</ul>{direct_link_html}"
        f'<p><a href="{video_url}">在 Bilibili 查看</a></p>'
    )
    attachments = (
        [
            {
                "url": playable_url,
                "mime_type": "video/mp4",
                "title": "视频 CDN 直链（无需 cookies，需要 Bilibili Referer）",
            }
        ]
        if playable_url
        else None
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
            "attachments": attachments,
        }
    )


VideoFetcher = Callable[[requests.Session, int, int], Awaitable[list[dict[str, Any]]]]
PlayableVideoUrlFetcher = Callable[[requests.Session, dict[str, Any]], Awaitable[str | None]]


async def fetch_user_feed_data(
    mid: int,
    page_size: int,
    cookies: str | None = None,
    *,
    fetch_videos: VideoFetcher = fetch_user_videos,
    fetch_playable_url: PlayableVideoUrlFetcher | None = None,
) -> tuple[BilibiliUserInfo | None, list[JSONFeedItem]]:
    headers = {**BILIBILI_HEADERS, "Referer": f"{BILIBILI_SPACE_BASE}/{mid}/video"}
    if cookies:
        headers["Cookie"] = cookies
    with requests.Session(headers=headers, timeout=30, impersonate="chrome136") as client:
        user = await fetch_user_info(client, mid)
        author = JSONFeedAuthor.model_validate(
            {
                "name": (user or {}).get("name") or str(mid),
                "url": f"{BILIBILI_SPACE_BASE}/{mid}",
                "avatar": (user or {}).get("face") or None,
            }
        )
        videos = await fetch_videos(client, mid, page_size)
        if fetch_playable_url:
            videos = await _attach_playable_video_urls(client, videos, fetch_playable_url)
        return user, [video_to_jsonfeed_item(video, author) for video in videos]


async def fetch_user_submissions_feed_data(
    mid: int, page_size: int, cookies: str | None = None
) -> tuple[BilibiliUserInfo | None, list[JSONFeedItem]]:
    """完整投稿列表 feed：基于 WBI /x/space/wbi/arc/search。"""
    return await fetch_user_feed_data(
        mid,
        page_size,
        cookies,
        fetch_videos=fetch_user_submissions,
        fetch_playable_url=fetch_playable_video_url,
    )
