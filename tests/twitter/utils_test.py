from rssapi.applications.twitter.types import Tweet
from rssapi.applications.twitter.utils import (
    content_html_from_tweet,
    title_from_text_by_delimiter_priority,
)


def test_title_from_text_by_delimiter_priority_without_truncation_chars():
    text = "hello world"
    assert title_from_text_by_delimiter_priority(text) == text


def test_title_from_text_by_delimiter_priority_truncates_on_newline():
    assert title_from_text_by_delimiter_priority("hello\nworld") == "hello"


def test_title_from_text_by_delimiter_priority_truncates_on_chinese_period():
    assert title_from_text_by_delimiter_priority("第一句。第二句") == "第一句"


def test_title_from_text_by_delimiter_priority_prefers_delimiter_order():
    assert title_from_text_by_delimiter_priority("第一句。\n第二句") == "第一句。"


def test_title_from_text_by_delimiter_priority_supports_custom_truncation_chars():
    assert title_from_text_by_delimiter_priority("hello!world", truncation_chars=("!",)) == "hello"


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
