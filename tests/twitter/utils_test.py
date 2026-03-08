import pytest

from rssapi.applications.twitter.types import Tweet
from rssapi.applications.twitter.utils import (
    content_html_from_tweet,
    text_without_http_links,
    text_without_tco_links,
    title_from_text_by_delimiter_priority,
)


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
