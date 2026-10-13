from rssapi.applications.youtube.utils import (
    YoutubeChannelSnippet,
    YoutubeVideoSnippet,
    video_to_jsonfeed_item,
)


def test_youtube_video_uses_channel_thumbnail_as_author_avatar() -> None:
    channel: YoutubeChannelSnippet = {
        "id": "channel-id",
        "title": "示例频道",
        "description": "频道简介",
        "customUrl": "@example",
        "thumbnails": "https://cdn.example/channel.jpg",
    }
    video: YoutubeVideoSnippet = {
        "id": "video-id",
        "title": "示例视频",
        "description": "视频简介",
        "thumbnails": "https://cdn.example/video.jpg",
        "publishedAt": "2025-01-01T00:00:00Z",
    }

    item = video_to_jsonfeed_item(channel, video)

    assert str(item.image) == "https://cdn.example/video.jpg"
    assert item.author and item.author.avatar == "https://cdn.example/channel.jpg"
    assert item.author.avatar != item.image
