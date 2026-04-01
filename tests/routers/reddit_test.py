import pytest
from rdt_cli.client import RedditClient

from rssapi.applications.reddit.types import PostData, SubredditAbout, SubredditListing
from rssapi.applications.reddit.utils import (
    _build_feed_item,
    _extract_gallery_images,
    _extract_preview_image,
    _extract_video,
    fetch_subreddit_feed,
)


@pytest.fixture(scope="module")
def raw_about() -> dict:
    with RedditClient() as rc:
        return rc.get_subreddit_about("aiyu")


@pytest.fixture(scope="module")
def raw_listing() -> dict:
    with RedditClient() as rc:
        return rc.get_subreddit("aiyu", limit=5)


# ── SubredditAbout model ────────────────────────────────────────


class TestSubredditAbout:
    def test_parse(self, raw_about: dict):
        about = SubredditAbout.model_validate(raw_about)
        assert about.display_name == "aiyu"
        assert about.display_name_prefixed == "r/aiyu"
        assert about.subscribers and about.subscribers > 0
        assert about.created_utc and about.created_utc > 0

    def test_description_present(self, raw_about: dict):
        about = SubredditAbout.model_validate(raw_about)
        assert about.public_description
        assert about.description

    def test_not_nsfw(self, raw_about: dict):
        about = SubredditAbout.model_validate(raw_about)
        assert about.over18 is False


# ── SubredditListing model ──────────────────────────────────────


class TestSubredditListing:
    def test_parse(self, raw_listing: dict):
        listing = SubredditListing.model_validate(raw_listing)
        assert listing.kind == "Listing"
        assert listing.data is not None
        assert listing.data.children
        assert len(listing.data.children) <= 5

    def test_children_have_post_data(self, raw_listing: dict):
        listing = SubredditListing.model_validate(raw_listing)
        assert listing.data is not None
        for child in listing.data.children or []:
            assert child.kind == "t3"
            assert child.data is not None
            assert child.data.id
            assert child.data.subreddit == "aiyu"

    def test_post_fields(self, raw_listing: dict):
        listing = SubredditListing.model_validate(raw_listing)
        assert listing.data is not None
        assert listing.data.children
        post = listing.data.children[0].data
        assert post is not None
        assert post.title
        assert post.author
        assert post.permalink
        assert post.created_utc and post.created_utc > 0


# ── Gallery extraction ──────────────────────────────────────────


class TestGalleryExtraction:
    @pytest.fixture(scope="class")
    def gallery_post(self, raw_listing: dict) -> PostData | None:
        listing = SubredditListing.model_validate(raw_listing)
        assert listing.data is not None
        for child in listing.data.children or []:
            if child.data and child.data.is_gallery:
                return child.data
        return None

    def test_gallery_post_exists(self, gallery_post: PostData | None):
        """r/aiyu is a fan sub with lots of gallery posts — at least one should appear in 5 items."""
        if gallery_post is None:
            pytest.skip("No gallery post in current listing")

    def test_gallery_metadata(self, gallery_post: PostData | None):
        if gallery_post is None:
            pytest.skip("No gallery post in current listing")
        assert gallery_post.media_metadata
        for item in gallery_post.media_metadata.values():
            assert item.status == "valid"
            assert item.s is not None
            assert item.s.u

    def test_extract_gallery_images(self, gallery_post: PostData | None):
        if gallery_post is None:
            pytest.skip("No gallery post in current listing")
        urls = _extract_gallery_images(gallery_post)
        assert urls
        for url in urls:
            assert url.startswith("https://")


# ── Preview extraction ──────────────────────────────────────────


class TestPreviewExtraction:
    def test_non_gallery_preview(self, raw_listing: dict):
        listing = SubredditListing.model_validate(raw_listing)
        assert listing.data is not None
        for child in listing.data.children or []:
            post = child.data
            if post and not post.is_gallery and post.preview:
                url = _extract_preview_image(post)
                assert url and url.startswith("https://")
                return
        pytest.skip("No non-gallery post with preview in current listing")

    def test_no_preview_returns_none(self):
        post = PostData()
        assert _extract_preview_image(post) is None


# ── Video extraction ─────────────────────────────────────────────


class TestVideoExtraction:
    def test_reddit_hosted_video(self):
        post = PostData(
            is_video=True,
            secure_media={
                "reddit_video": {
                    "fallback_url": "https://v.redd.it/abc123/DASH_720.mp4",
                    "height": 720,
                    "width": 1280,
                }
            },
        )
        result = _extract_video(post)
        assert result is not None
        assert result["type"] == "reddit"
        assert result["url"] == "https://v.redd.it/abc123/DASH_720.mp4"

    def test_oembed_video(self):
        post = PostData(
            media={
                "oembed": {
                    "type": "video",
                    "html": '<iframe src="https://www.youtube.com/embed/xyz"></iframe>',
                }
            },
        )
        result = _extract_video(post)
        assert result is not None
        assert result["type"] == "oembed"
        assert "youtube.com" in result["html"]

    def test_no_video(self):
        post = PostData(title="just text")
        assert _extract_video(post) is None

    def test_video_title_prefix(self):
        post = PostData(
            id="v1",
            title="Cool video",
            is_video=True,
            permalink="/r/test/comments/v1/cool_video/",
            created_utc=1700000000.0,
            secure_media={"reddit_video": {"fallback_url": "https://v.redd.it/abc/DASH_720.mp4"}},
        )
        item = _build_feed_item(post)
        assert item.title is not None
        assert item.title.startswith("▶️")
        assert item.content_html is not None
        assert "<video" in item.content_html


# ── Feed item building ──────────────────────────────────────────


class TestBuildFeedItem:
    def test_build(self, raw_listing: dict):
        listing = SubredditListing.model_validate(raw_listing)
        assert listing.data is not None
        assert listing.data.children
        post = listing.data.children[0].data
        assert post is not None
        item = _build_feed_item(post)
        assert item.id == post.id
        assert post.title
        assert item.title and post.title in item.title
        assert item.url and item.url.startswith("https://www.reddit.com/")
        assert item.content_html
        assert item.date_published
        assert item.author

    def test_gallery_post_has_images_in_html(self, raw_listing: dict):
        listing = SubredditListing.model_validate(raw_listing)
        assert listing.data is not None
        for child in listing.data.children or []:
            if child.data and child.data.is_gallery and child.data.media_metadata:
                item = _build_feed_item(child.data)
                assert item.content_html and "<img " in item.content_html
                return
        pytest.skip("No gallery post in current listing")


# ── fetch_subreddit_feed integration ───────────────────────────


class TestFetchSubredditFeed:
    def test_returns_about_and_items(self):
        about, items = fetch_subreddit_feed("aiyu", 3, None)
        assert isinstance(about, SubredditAbout)
        assert about.display_name == "aiyu"
        assert len(items) <= 3
        assert all(item.id for item in items)
