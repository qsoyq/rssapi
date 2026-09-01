import importlib.metadata
import time
from typing import Literal

from pydantic_settings import BaseSettings, SettingsConfigDict

from rssapi.utils.basic import get_date_string_for_shanghai

run_at_ts = int(time.time())
run_at = get_date_string_for_shanghai(run_at_ts)
version = importlib.metadata.version("rssapi")


class MiddlewareSettings(BaseSettings):
    model_config = SettingsConfigDict(
        env_prefix="RSS_MIDDLEWARE_",
        env_file=".env",
        extra="ignore",
    )
    max_title_length: int = 50


class TwitterSettings(BaseSettings):
    model_config = SettingsConfigDict(
        env_prefix="RSS_TWITTER_",
        env_file=".env",
        extra="ignore",
    )
    fetch_concurrency: int = 5
    user_posts_cache_ttl: int = 14400
    user_posts_cache_maxsize: int = 4096
    feed_cache_ttl: int = 3600
    feed_cache_maxsize: int = 4096
    client_transaction_signer_enabled: bool = True
    client_transaction_bootstrap_url: str = "https://x.com/skyseafor"
    browser_fallback_enabled: bool = True


class RedditSettings(BaseSettings):
    model_config = SettingsConfigDict(
        env_prefix="RSS_REDDIT_",
        env_file=".env",
        extra="ignore",
    )
    dash_proxy_host: str = "https://p.19940731.xyz"
    user_posts_cache_ttl: int = 600
    user_posts_cache_maxsize: int = 4096


class GithubSettings(BaseSettings):
    model_config = SettingsConfigDict(
        env_prefix="RSS_GITHUB_",
        env_file=".env",
        extra="ignore",
    )
    release_cache_ttl: int = 300
    release_cache_maxsize: int = 4096
    notification_cache_ttl: int = 300
    notification_cache_maxsize: int = 4096
    commit_cache_ttl: int = 1800
    commit_cache_maxsize: int = 4096
    issue_cache_ttl: int = 1800
    issue_cache_maxsize: int = 4096


class V2flySettings(BaseSettings):
    model_config = SettingsConfigDict(
        env_prefix="RSS_V2FLY_",
        env_file=".env",
        extra="ignore",
    )
    geosite_name_cache_ttl: int = 43200
    geosite_name_cache_maxsize: int = 4096
    geosite_library_cache_ttl: int = 43200
    geosite_library_cache_maxsize: int = 16


class GofansSettings(BaseSettings):
    model_config = SettingsConfigDict(
        env_prefix="RSS_GOFANS_",
        env_file=".env",
        extra="ignore",
    )
    cache_ttl: int = 3600
    cache_maxsize: int = 4096


class V2exSettings(BaseSettings):
    model_config = SettingsConfigDict(
        env_prefix="RSS_V2EX_",
        env_file=".env",
        extra="ignore",
    )
    cache_ttl: int = 600
    cache_maxsize: int = 4096


class LoonSettings(BaseSettings):
    model_config = SettingsConfigDict(
        env_prefix="RSS_LOON_",
        env_file=".env",
        extra="ignore",
    )
    cache_ttl: int = 1800
    cache_maxsize: int = 4096


class ReadhubSettings(BaseSettings):
    model_config = SettingsConfigDict(
        env_prefix="RSS_READHUB_",
        env_file=".env",
        extra="ignore",
    )
    cache_ttl: int = 900
    cache_maxsize: int = 4096


class TelegramSettings(BaseSettings):
    model_config = SettingsConfigDict(
        env_prefix="RSS_TELEGRAM_",
        env_file=".env",
        extra="ignore",
    )
    cache_ttl: int = 900
    cache_maxsize: int = 4096


class Day1024Settings(BaseSettings):
    model_config = SettingsConfigDict(
        env_prefix="RSS_DAY1024_",
        env_file=".env",
        extra="ignore",
    )
    cache_ttl: int = 3600
    cache_maxsize: int = 4096


class NgaSettings(BaseSettings):
    model_config = SettingsConfigDict(
        env_prefix="RSS_NGA_",
        env_file=".env",
        extra="ignore",
    )
    cache_ttl: int = 300
    cache_maxsize: int = 4096
    sections_cache_ttl: int = 86400
    sections_cache_maxsize: int = 1024
    smiles_cache_ttl: int = 86400 * 3
    smiles_cache_maxsize: int = 1024
    smiles_preload_enable: bool = True
    thread_detail_cache_ttl: int = 86400
    thread_detail_cache_maxsize: int = 4096


class NodeseekSettings(BaseSettings):
    model_config = SettingsConfigDict(
        env_prefix="RSS_NODESEEK_",
        env_file=".env",
        extra="ignore",
    )
    cache_ttl: int = 600
    cache_maxsize: int = 4096
    article_post_cache_ttl: int = 86400 * 3
    article_post_cache_maxsize: int = 4096
    login_required_cache_ttl: int = 86400 * 3
    login_required_cache_maxsize: int = 4096


class YoutubeSettings(BaseSettings):
    model_config = SettingsConfigDict(
        env_prefix="RSS_YOUTUBE_",
        env_file=".env",
        extra="ignore",
    )
    channel_feed_cache_ttl: int = 3600
    channel_feed_cache_maxsize: int = 4096


class DouyinSettings(BaseSettings):
    model_config = SettingsConfigDict(
        env_prefix="RSS_DOUYIN_",
        env_file=".env",
        extra="ignore",
    )
    user_feeds_cache_ttl: int = 1800
    user_feeds_cache_maxsize: int = 4096


class BilibiliSettings(BaseSettings):
    model_config = SettingsConfigDict(
        env_prefix="RSS_BILIBILI_",
        env_file=".env",
        extra="ignore",
    )
    user_videos_cache_ttl: int = 900
    user_videos_cache_maxsize: int = 4096
    media_url_template: str | None = None
    playable_url_fetch_concurrency: int = 5


class InstagramSettings(BaseSettings):
    model_config = SettingsConfigDict(
        env_prefix="RSS_INSTAGRAM_",
        env_file=".env",
        extra="ignore",
    )
    app_id: str = "936619743392459"
    user_posts_cache_ttl: int = 10800
    user_posts_cache_maxsize: int = 4096


class TikTokSettings(BaseSettings):
    model_config = SettingsConfigDict(
        env_prefix="RSS_TIKTOK_",
        env_file=".env",
        extra="ignore",
    )
    user_posts_cache_ttl: int = 10800
    user_posts_cache_maxsize: int = 4096
    request_timeout: float = 20.0
    fetch_concurrency: int = 3
    media_proxy_concurrency: int = 3
    playwright_timeout: float = 35.0
    playwright_queue_timeout: float = 35.0
    playwright_startup_timeout: float = 5.0
    playwright_navigation_timeout: float = 15.0
    playwright_concurrency: int = 1
    playwright_max_inflight: int = 3
    playwright_storage_state_path: str | None = None
    cookie_query_enabled: bool = True
    v2_media_mode: Literal["direct", "proxy"] = "direct"
    proxy: str | None = None


class AppSettings(BaseSettings):  # type:ignore
    api_prefix: str = "/api"
    basic_auth_user: str = "root"
    basic_auth_passwd: str = "example"

    twitter: TwitterSettings = TwitterSettings()
    reddit: RedditSettings = RedditSettings()
    middleware: MiddlewareSettings = MiddlewareSettings()
    github: GithubSettings = GithubSettings()
    v2fly: V2flySettings = V2flySettings()
    gofans: GofansSettings = GofansSettings()
    v2ex: V2exSettings = V2exSettings()
    loon: LoonSettings = LoonSettings()
    readhub: ReadhubSettings = ReadhubSettings()
    telegram: TelegramSettings = TelegramSettings()
    day1024: Day1024Settings = Day1024Settings()
    nga: NgaSettings = NgaSettings()
    nodeseek: NodeseekSettings = NodeseekSettings()
    youtube: YoutubeSettings = YoutubeSettings()
    douyin: DouyinSettings = DouyinSettings()
    bilibili: BilibiliSettings = BilibiliSettings()
    instagram: InstagramSettings = InstagramSettings()
    tiktok: TikTokSettings = TikTokSettings()

    cloud_scraper_verify: bool = False
    rss_playwright_concurrency: int = 11
    # rss
    ## douyin
    rss_douyin_user_semaphore: int = 5
    rss_douyin_user_auto_fetch_timeout: float = 60
    rss_douyin_user_auto_fetch_start_wait: float = 30
    rss_douyin_user_auto_fetch_enable: bool = False
    rss_douyin_user_auto_fetch_wait: int = 600
    rss_douyin_user_auto_fetch_once_wait: int = 10
    rss_douyin_user_history_storage: str = "~/.rssapi/rss.douyin.user.history"
    rss_douyin_user_headless: bool = True

    # meta
    model_config = SettingsConfigDict(env_file=".env", extra="ignore")


settings = AppSettings()
