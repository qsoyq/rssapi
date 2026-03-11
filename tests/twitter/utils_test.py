import logging
import sys
import types
from types import SimpleNamespace
from typing import Any, TypedDict, cast

import pytest

twitter_cli_module = cast(Any, sys.modules.setdefault("twitter_cli", types.ModuleType("twitter_cli")))
twitter_auth_module = cast(Any, sys.modules.setdefault("twitter_cli.auth", types.ModuleType("twitter_cli.auth")))
twitter_client_module = cast(Any, sys.modules.setdefault("twitter_cli.client", types.ModuleType("twitter_cli.client")))
twitter_config_module = cast(Any, sys.modules.setdefault("twitter_cli.config", types.ModuleType("twitter_cli.config")))

if not hasattr(twitter_auth_module, "extract_from_browser"):
    twitter_auth_module.extract_from_browser = lambda: None
if not hasattr(twitter_auth_module, "get_cookies"):
    twitter_auth_module.get_cookies = lambda: {}
if not hasattr(twitter_client_module, "TwitterClient"):

    class _StubTwitterClient:
        def __init__(self, *args, **kwargs):
            pass

    twitter_client_module.TwitterClient = _StubTwitterClient
if not hasattr(twitter_config_module, "load_config"):
    twitter_config_module.load_config = lambda: {}

twitter_cli_module.auth = twitter_auth_module
twitter_cli_module.client = twitter_client_module
twitter_cli_module.config = twitter_config_module

from rssapi.applications.twitter import patch as twitter_patch  # noqa: E402
from rssapi.applications.twitter import utils as twitter_utils  # noqa: E402
from rssapi.applications.twitter.feed import _tweets_to_jsonfeed_items  # noqa: E402
from rssapi.applications.twitter.types import Tweet  # noqa: E402
from rssapi.applications.twitter.utils import (  # noqa: E402
    content_html_from_tweet,
    text_without_http_links,
    text_without_tco_links,
    title_emoji_prefix_from_tweet,
    title_from_text_by_delimiter_priority,
)


class _RetryCalls(TypedDict):
    count: int
    max_retries: list[int]


@pytest.mark.parametrize(
    ("text", "expected", "truncation_chars"),
    [
        ("hello world", "hello world", None),
        ("hello\nworld", "hello", None),
        ("第一句。第二句", "第一句", None),
        ("Is this working? Yes", "Is this working", None),
        ("Breaking news! Details below", "Breaking news", None),
        ("第一句。\n第二句", "第一句。", None),
        ("hello!world", "hello", ("!",)),
        (
            "Mole now supports Windows. The first pre-release is here. To keep the Mac version simple and lightweight, the Windows support lives in a separate branch. ",
            "Mole now supports Windows",
            None,
        ),
    ],
)
def test_title_from_text_by_delimiter_priority(text: str, expected: str, truncation_chars: tuple[str, ...] | None):
    assert title_from_text_by_delimiter_priority(text, truncation_chars=truncation_chars) == expected


def test_text_without_http_links_removes_multiple_links_and_normalizes_spaces():
    assert (
        text_without_http_links("hello https://example.com world http://test.com/path?q=1\nnext line")
        == "hello world\nnext line"
    )


def test_text_without_tco_links_removes_only_strict_tco_links():
    assert (
        text_without_tco_links(
            "hello https://t.co/DlBA3uySC1 world https://example.com/a "
            "https://nott.co/DlBA3uySC1 https://t.co.uk/DlBA3uySC1"
        )
        == "hello world https://example.com/a https://nott.co/DlBA3uySC1 https://t.co.uk/DlBA3uySC1"
    )


@pytest.mark.parametrize(
    ("func", "text", "expected"),
    [
        (text_without_http_links, "hello \t  https://example.com \n\tworld", "hello\nworld"),
        (text_without_tco_links, "hello \t  https://t.co/DlBA3uySC1 \n\tworld", "hello\nworld"),
    ],
)
def test_link_removal_normalizes_whitespace_around_newlines(func, text: str, expected: str):
    assert func(text) == expected


def test_parse_cookie_header_trims_entries_and_ignores_invalid_chunks():
    assert twitter_utils._parse_cookie_header(" auth_token = token ; invalid ; ; ct0 = csrf ; theme = dark ") == {
        "auth_token": "token",
        "ct0": "csrf",
        "theme": "dark",
    }


def test_mock_twitter_extract_from_browser_restores_original_function(monkeypatch: pytest.MonkeyPatch):
    def fake_extract_from_browser():
        return "original"

    monkeypatch.setattr(twitter_utils.twitter_auth, "extract_from_browser", fake_extract_from_browser)

    with twitter_utils._mock_twitter_extract_from_browser():
        with pytest.raises(RuntimeError, match="disabled"):
            twitter_utils.twitter_auth.extract_from_browser()

    assert twitter_utils.twitter_auth.extract_from_browser is fake_extract_from_browser


def test_build_twitter_client_prefers_explicit_tokens(monkeypatch: pytest.MonkeyPatch):
    captured: dict[str, object] = {}

    class FakeTwitterClient:
        def __init__(
            self, auth_token: str, ct0: str, rate_limit_config: dict[str, int], cookie_string: str | None = None
        ):
            captured["auth_token"] = auth_token
            captured["ct0"] = ct0
            captured["rate_limit_config"] = rate_limit_config
            captured["cookie_string"] = cookie_string

    monkeypatch.setattr(twitter_utils, "load_config", lambda: {"rateLimit": {"limit": 10}})
    monkeypatch.setattr(twitter_utils, "TwitterClient", FakeTwitterClient)
    monkeypatch.setattr(
        twitter_utils.twitter_auth,
        "get_cookies",
        lambda: pytest.fail("get_cookies should not be called when auth_token and ct0 are provided"),
    )

    client = twitter_utils._build_twitter_client("token", "csrf", cookie_string="auth_token=token; ct0=csrf")

    assert isinstance(client, FakeTwitterClient)
    assert captured == {
        "auth_token": "token",
        "ct0": "csrf",
        "rate_limit_config": {"limit": 10},
        "cookie_string": "auth_token=token; ct0=csrf",
    }


def test_install_twitter_client_429_no_retry_patch_disables_http_429_retry_for_api_request(
    monkeypatch: pytest.MonkeyPatch, caplog: pytest.LogCaptureFixture
):
    calls = {"count": 0}

    class FakeTwitterAPIError(RuntimeError):
        def __init__(self, status_code: int, message: str):
            super().__init__(message)
            self.status_code = status_code

    class FakeResponse:
        status_code = 429
        text = "rate limited"

    class FakeSession:
        def get(self, url: str, headers: dict[str, str], timeout: int) -> FakeResponse:
            calls["count"] += 1
            return FakeResponse()

    def fake_get_cffi_session() -> FakeSession:
        return FakeSession()

    class FakeClient:
        def __init__(self):
            self._max_retries = 3
            self._retry_base_delay = 1.0

        def _build_headers(self, url: str = "", method: str = "GET") -> dict[str, str]:
            return {}

        def _api_request(self, url: str, method: str = "GET", body: dict[str, object] | None = None):
            raise AssertionError("should be replaced by monkey patch")

    monkeypatch.setitem(FakeClient._api_request.__globals__, "_get_cffi_session", fake_get_cffi_session)
    monkeypatch.setitem(FakeClient._api_request.__globals__, "TwitterAPIError", FakeTwitterAPIError)
    monkeypatch.setattr(twitter_patch, "TwitterClient", FakeClient)

    twitter_patch.install_twitter_client_429_no_retry_patch()

    client = FakeClient()
    with caplog.at_level(logging.WARNING):
        with pytest.raises(FakeTwitterAPIError, match="429"):
            client._api_request("https://example.com")

    assert calls["count"] == 1
    assert "skipping retry and aborting request" in caplog.text


def test_install_twitter_client_429_no_retry_patch_falls_back_to_api_get(
    monkeypatch: pytest.MonkeyPatch, caplog: pytest.LogCaptureFixture
):
    calls: _RetryCalls = {"count": 0, "max_retries": []}

    class FakeTwitterAPIError(RuntimeError):
        def __init__(self, status_code: int, message: str):
            super().__init__(message)
            self.status_code = status_code

    class FakeClient:
        def __init__(self):
            self._max_retries = 5

        def _api_get(self, url: str):
            calls["count"] += 1
            calls["max_retries"].append(self._max_retries)
            raise FakeTwitterAPIError(429, "Twitter API error 429: rate limited")

    monkeypatch.setattr(twitter_patch, "TwitterClient", FakeClient)

    twitter_patch.install_twitter_client_429_no_retry_patch()

    client = FakeClient()
    with caplog.at_level(logging.WARNING):
        with pytest.raises(FakeTwitterAPIError, match="429"):
            client._api_get("https://example.com")

    assert calls["count"] == 1
    assert calls["max_retries"] == [0]
    assert client._max_retries == 5
    assert "skipping retry and aborting request" in caplog.text


@pytest.mark.parametrize(
    ("feed_type", "expected_result"),
    [("following", ["following-feed"]), ("for-you", ["home-feed"])],
)
def test_fetch_feed_sync_uses_expected_client_method(
    monkeypatch: pytest.MonkeyPatch, feed_type: str, expected_result: list[str]
):
    captured: dict[str, object] = {}

    class FakeClient:
        def fetch_following_feed(self, max_tweets: int) -> list[str]:
            captured["called"] = ("following", max_tweets)
            return ["following-feed"]

        def fetch_home_timeline(self, max_tweets: int) -> list[str]:
            captured["called"] = ("home", max_tweets)
            return ["home-feed"]

    monkeypatch.setattr(
        twitter_utils,
        "_build_twitter_client",
        lambda auth_token, ct0, cookie_string=None: (
            captured.update(
                {
                    "auth_token": auth_token,
                    "ct0": ct0,
                    "cookie_string": cookie_string,
                }
            )
            or FakeClient()
        ),
    )
    monkeypatch.setattr(twitter_utils, "_to_rssapi_tweets", lambda tweets: tweets)

    tweets = twitter_utils._fetch_feed_sync(20, "auth_token=token; ct0=csrf", feed_type)

    assert tweets == expected_result
    assert captured["auth_token"] == "token"
    assert captured["ct0"] == "csrf"
    assert captured["cookie_string"] == "auth_token=token; ct0=csrf"
    assert captured["called"] == (("following", 20) if feed_type == "following" else ("home", 20))


def test_fetch_user_posts_sync_filters_by_screen_name_and_keeps_retweets(monkeypatch: pytest.MonkeyPatch):
    def make_tweet(tweet_id: str, screen_name: str, *, is_retweet: bool = False) -> Tweet:
        return Tweet.model_validate(
            {
                "id": tweet_id,
                "text": f"tweet-{tweet_id}",
                "author": {"name": screen_name, "screenName": screen_name},
                "metrics": {},
                "createdAt": "2025-01-01T00:00:00+00:00",
                "media": [],
                "isRetweet": is_retweet,
            }
        )

    fake_client = SimpleNamespace(
        fetch_user=lambda screen_name: SimpleNamespace(id=f"user-{screen_name}"),
        fetch_user_tweets=lambda user_id, max_tweets: ["ignored-raw-tweets"],
    )

    monkeypatch.setattr(
        twitter_utils, "_build_twitter_client", lambda auth_token, ct0, cookie_string=None: fake_client
    )
    monkeypatch.setattr(
        twitter_utils,
        "_to_rssapi_tweets",
        lambda tweets: [
            make_tweet("1", "TargetUser"),
            make_tweet("2", "TARGETUSER"),
            make_tweet("3", "SomeoneElse"),
            make_tweet("4", "SomeoneElse", is_retweet=True),
        ],
    )

    tweets = twitter_utils._fetch_user_posts_sync("targetuser", 10, "auth_token=token; ct0=csrf")

    assert [tweet.id for tweet in tweets] == ["1", "2", "4"]


def test_content_html_from_tweet_renders_photo_and_animated_gif_as_image():
    tweet = Tweet.model_validate(
        {
            "id": "1",
            "text": "hello",
            "author": {"name": "tester", "screenName": "tester"},
            "metrics": {},
            "createdAt": "2025-01-01T00:00:00+00:00",
            "media": [
                {
                    "type": "animated_gif",
                    "url": "https://example.com/animated.gif",
                    "width": 320,
                    "height": 180,
                }
            ],
        }
    )

    assert content_html_from_tweet(tweet) == (
        '<p>hello</p><img src="https://example.com/animated.gif" width="320" height="180" />'
    )


def test_content_html_from_tweet_removes_tco_links_from_text():
    tweet = Tweet.model_validate(
        {
            "id": "1",
            "text": "hello https://t.co/DlBA3uySC1 world https://example.com/keep",
            "author": {"name": "tester", "screenName": "tester"},
            "metrics": {},
            "createdAt": "2025-01-01T00:00:00+00:00",
            "media": [],
        }
    )

    assert content_html_from_tweet(tweet) == "<p>hello world https://example.com/keep</p>"

    tweet = Tweet.model_validate(
        {
            "id": "1",
            "text": "hello",
            "author": {"name": "tester", "screenName": "tester"},
            "metrics": {},
            "createdAt": "2025-01-01T00:00:00+00:00",
            "media": [
                {
                    "type": "photo",
                    "url": "https://example.com/animated.gif",
                    "width": 320,
                    "height": 180,
                }
            ],
        }
    )

    assert content_html_from_tweet(tweet) == (
        '<p>hello</p><img src="https://example.com/animated.gif" width="320" height="180" />'
    )


def test_content_html_from_tweet_renders_video_without_emoji_prefix():
    tweet = Tweet.model_validate(
        {
            "id": "1",
            "text": "hello",
            "author": {"name": "tester", "screenName": "tester"},
            "metrics": {},
            "createdAt": "2025-01-01T00:00:00+00:00",
            "media": [
                {
                    "type": "video",
                    "url": "https://example.com/video.mp4",
                    "width": 640,
                    "height": 360,
                }
            ],
        }
    )

    assert content_html_from_tweet(tweet) == (
        '<p>hello</p><video src="https://example.com/video.mp4" width="640" height="360" controls preload="metadata"></video>'
    )


def test_title_emoji_prefix_from_tweet_includes_media_and_retweet_prefixes():
    tweet = Tweet.model_validate(
        {
            "id": "1",
            "text": "hello",
            "author": {"name": "tester", "screenName": "tester"},
            "metrics": {},
            "createdAt": "2025-01-01T00:00:00+00:00",
            "isRetweet": True,
            "media": [
                {
                    "type": "photo",
                    "url": "https://example.com/image.jpg",
                    "width": 320,
                    "height": 180,
                },
                {
                    "type": "video",
                    "url": "https://example.com/video.mp4",
                    "width": 640,
                    "height": 360,
                },
            ],
        }
    )

    assert title_emoji_prefix_from_tweet(tweet) == "▶️ 📸 🔁"


def test_tweets_to_jsonfeed_items_moves_media_emoji_to_title():
    tweet = Tweet.model_validate(
        {
            "id": "1",
            "text": "hello https://t.co/DlBA3uySC1 world",
            "author": {"name": "tester", "screenName": "tester"},
            "metrics": {},
            "createdAt": "2025-01-01T00:00:00+00:00",
            "media": [
                {
                    "type": "photo",
                    "url": "https://example.com/image.jpg",
                    "width": 320,
                    "height": 180,
                }
            ],
        }
    )

    item = _tweets_to_jsonfeed_items([tweet])[0]

    assert item.title == "📸 hello world"
    assert (
        item.content_html == '<p>hello world</p><img src="https://example.com/image.jpg" width="320" height="180" />'
    )
