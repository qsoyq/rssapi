from rssapi.applications.douyin.router import douyin_user_feeds_handler
from rssapi.applications.rss.schemas.rss.jsonfeed import JSONFeedItem


def test_douyin_user_handler_keeps_author_avatar_separate_from_item_image() -> None:
    item = JSONFeedItem.model_validate(
        {
            "id": "douyin-1",
            "content_text": "正文",
            "image": "https://cdn.example/cover.jpg",
            "author": {
                "name": "作者",
                "url": "https://www.douyin.com/user/creator",
                "avatar": "https://cdn.example/avatar.jpg",
            },
        }
    )
    feed: dict = {"icon": "https://www.douyin.com/favicon.ico", "favicon": "https://www.douyin.com/favicon.ico"}

    douyin_user_feeds_handler(feed, [item])

    assert item.author and item.author.avatar == "https://cdn.example/avatar.jpg"
    assert item.author.avatar != item.image
    assert feed["icon"] == "https://cdn.example/avatar.jpg"
