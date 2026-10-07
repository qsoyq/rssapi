import json
from collections.abc import Iterator
from dataclasses import asdict
from functools import partial
from http.server import SimpleHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from threading import Thread
from typing import Any, cast

import pytest
from bs4 import BeautifulSoup
from twitter_cli.parser import parse_timeline_response

from rssapi.applications.twitter.feed import _tweets_to_jsonfeed_items
from rssapi.applications.twitter.types import Tweet, TweetMedia
from rssapi.applications.twitter.utils import (
    MyTwitterClient,
    _to_rssapi_tweets,
    _video_posters_from_response,
    content_html_from_tweet,
)
from rssapi.core.settings import settings


def _video(key: str, poster: str | None) -> dict[str, Any]:
    media: dict[str, Any] = {
        "type": "video",
        "original_info": {"width": 640, "height": 360},
        "video_info": {
            "variants": [
                {"content_type": "application/x-mpegURL", "url": f"https://video.twimg.com/{key}.m3u8"},
                {"content_type": "video/mp4", "bitrate": 256000, "url": f"https://video.twimg.com/{key}-low.mp4"},
                {"content_type": "video/mp4", "bitrate": 832000, "url": f"https://video.twimg.com/{key}-high.mp4"},
            ]
        },
    }
    if poster is not None:
        media["media_url_https"] = poster
    return media


def _tweet_result(tweet_id: str, media: list[dict[str, Any]]) -> dict[str, Any]:
    return {
        "__typename": "Tweet",
        "rest_id": tweet_id,
        "core": {
            "user_results": {
                "result": {
                    "rest_id": "user-1",
                    "legacy": {"name": "Tester", "screen_name": "tester"},
                }
            }
        },
        "legacy": {
            "full_text": "A video",
            "created_at": "Wed Oct 07 00:45:00 +0000 2026",
            "extended_entities": {"media": media},
        },
    }


def _timeline(results: list[dict[str, Any]]) -> dict[str, Any]:
    return {
        "data": {
            "instructions": [
                {
                    "entries": [
                        {"content": {"itemContent": {"tweet_results": {"result": result}}}} for result in results
                    ]
                }
            ]
        }
    }


def _parse_timeline(response: dict[str, Any]) -> list[Any]:
    tweets, _ = parse_timeline_response(response, lambda data: data["data"]["instructions"])
    return cast(list[Any], tweets)


@pytest.fixture
def response_server(tmp_path: Path) -> Iterator[tuple[Path, str]]:
    """Serve local GraphQL fixtures over real HTTP without contacting Twitter."""
    handler = partial(SimpleHTTPRequestHandler, directory=str(tmp_path))
    server = ThreadingHTTPServer(("127.0.0.1", 0), handler)
    thread = Thread(target=server.serve_forever, daemon=True)
    signer_enabled = settings.twitter.client_transaction_signer_enabled
    settings.twitter.client_transaction_signer_enabled = False
    thread.start()
    try:
        yield tmp_path, f"http://127.0.0.1:{server.server_port}"
    finally:
        server.shutdown()
        server.server_close()
        thread.join()
        settings.twitter.client_transaction_signer_enabled = signer_enabled


def test_video_poster_survives_http_parser_conversion_and_jsonfeed(response_server: tuple[Path, str]) -> None:
    directory, base_url = response_server
    first_poster = "https://pbs.twimg.com/amplify_video_thumb/first.jpg"
    second_poster = "https://pbs.twimg.com/ext_tw_video_thumb/second.jpg"
    response = _timeline([_tweet_result("1", [_video("first", first_poster), _video("second", second_poster)])])
    (directory / "page.json").write_text(json.dumps(response), encoding="utf-8")
    client = MyTwitterClient("test-token", "test-csrf")

    fetched_response = client._api_request(f"{base_url}/page.json")
    assert fetched_response == response
    parsed = _parse_timeline(fetched_response)
    assert "poster_url" not in asdict(parsed[0])["media"][0]
    assert client.video_posters == {
        "https://video.twimg.com/first-low.mp4": first_poster,
        "https://video.twimg.com/first-high.mp4": first_poster,
        "https://video.twimg.com/second-low.mp4": second_poster,
        "https://video.twimg.com/second-high.mp4": second_poster,
    }

    tweets = _to_rssapi_tweets(parsed, client.video_posters)
    item = _tweets_to_jsonfeed_items(tweets)[0]
    videos = BeautifulSoup(item.content_html, "html.parser").find_all("video")
    assert [(video["src"], video["poster"]) for video in videos] == [
        ("https://video.twimg.com/first-high.mp4", first_poster),
        ("https://video.twimg.com/second-high.mp4", second_poster),
    ]
    assert all(video["width"] == "640" and video["height"] == "360" for video in videos)
    assert all(video.has_attr("controls") and video["preload"] == "metadata" for video in videos)


def test_video_posters_cover_retweets_and_quoted_tweets() -> None:
    original = _tweet_result("1", [_video("original", "https://pbs.twimg.com/original.jpg")])
    original["quoted_status_result"] = {
        "result": _tweet_result("2", [_video("quoted", "https://pbs.twimg.com/quoted.jpg")])
    }
    retweet = _tweet_result("3", [])
    retweet["legacy"]["retweeted_status_result"] = {
        "result": {"__typename": "TweetWithVisibilityResults", "tweet": original}
    }
    response = _timeline([retweet])

    tweet = _to_rssapi_tweets(_parse_timeline(response), _video_posters_from_response(response))[0]
    assert tweet.is_retweet
    assert tweet.id == "1"
    assert tweet.quoted_tweet is not None
    assert tweet.media[0].poster_url == "https://pbs.twimg.com/original.jpg"
    assert tweet.quoted_tweet.media[0].poster_url == "https://pbs.twimg.com/quoted.jpg"
    videos = BeautifulSoup(content_html_from_tweet(tweet), "html.parser").find_all("video")
    assert [video["poster"] for video in videos] == [
        "https://pbs.twimg.com/original.jpg",
        "https://pbs.twimg.com/quoted.jpg",
    ]


def test_video_posters_accumulate_across_pages_and_stay_on_the_client(response_server: tuple[Path, str]) -> None:
    directory, base_url = response_server
    client = MyTwitterClient("test-token", "test-csrf")
    parsed: list[Any] = []
    for tweet_id in ("1", "2"):
        response = _timeline([_tweet_result(tweet_id, [_video(tweet_id, f"https://pbs.twimg.com/{tweet_id}.jpg")])])
        (directory / f"{tweet_id}.json").write_text(json.dumps(response), encoding="utf-8")
        parsed.extend(_parse_timeline(client._api_request(f"{base_url}/{tweet_id}.json")))

    tweets = _to_rssapi_tweets(parsed, client.video_posters)
    assert [tweet.media[0].poster_url for tweet in tweets] == [
        "https://pbs.twimg.com/1.jpg",
        "https://pbs.twimg.com/2.jpg",
    ]
    other_client = MyTwitterClient("test-token", "test-csrf")
    assert other_client.video_posters == {}
    assert all(tweet.media[0].poster_url is None for tweet in _to_rssapi_tweets(parsed, other_client.video_posters))


@pytest.mark.parametrize("poster", [None, "", "   "])
def test_missing_video_thumbnail_keeps_playable_video_without_poster(poster: str | None) -> None:
    response = _timeline([_tweet_result("1", [_video("missing", poster)])])
    posters = _video_posters_from_response(response)
    assert posters == {}
    tweet = _to_rssapi_tweets(_parse_timeline(response), posters)[0]
    video = BeautifulSoup(content_html_from_tweet(tweet), "html.parser").find("video")
    assert video is not None
    assert video["src"] == "https://video.twimg.com/missing-high.mp4"
    assert not video.has_attr("poster")


@pytest.mark.parametrize("poster", [None, "", 'https://pbs.twimg.com/cover.jpg?name=large&label="cover"'])
def test_video_poster_attribute_is_optional_and_escaped(poster: str | None) -> None:
    tweet = Tweet.model_validate(
        {
            "id": "1",
            "text": "",
            "author": {"name": "Tester", "screenName": "tester"},
            "metrics": {},
            "createdAt": "2026-10-07T00:45:00+00:00",
            "media": [{"type": "video", "url": "https://video.twimg.com/video.mp4", "poster_url": poster}],
        }
    )
    rendered = content_html_from_tweet(tweet)
    video = BeautifulSoup(rendered, "html.parser").find("video")
    assert video is not None
    if poster:
        assert video["poster"] == poster
        assert "&amp;label=&quot;cover&quot;" in rendered
    else:
        assert not video.has_attr("poster")


def test_thumbnail_collection_ignores_images_gifs_and_malformed_media() -> None:
    photo = _video("photo", "https://pbs.twimg.com/photo.jpg")
    photo["type"] = "photo"
    gif = _video("gif", "https://pbs.twimg.com/gif.jpg")
    gif["type"] = "animated_gif"
    malformed = [
        {"type": "video", "media_url_https": "https://pbs.twimg.com/a.jpg", "video_info": None},
        {"type": "video", "media_url_https": 1, "video_info": {"variants": []}},
        {"type": "video", "media_url_https": "https://pbs.twimg.com/b.jpg", "video_info": {"variants": None}},
        {
            "type": "video",
            "media_url_https": "https://pbs.twimg.com/c.jpg",
            "video_info": {"variants": [None, {"content_type": "video/mp4", "url": None}]},
        },
    ]
    assert _video_posters_from_response({"media": [photo, gif, *malformed], "other": None}) == {}
    assert TweetMedia(type="video", url="https://video.twimg.com/video.mp4").poster_url is None
