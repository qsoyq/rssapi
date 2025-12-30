import importlib.metadata
import time

from pydantic_settings import BaseSettings, SettingsConfigDict

from rssapi.utils.basic import get_date_string_for_shanghai

run_at_ts = int(time.time())
run_at = get_date_string_for_shanghai(run_at_ts)
version = importlib.metadata.version('rssapi')


class AppSettings(BaseSettings):  # type:ignore
    api_prefix: str = '/api'
    basic_auth_user: str = 'root'
    basic_auth_passwd: str = 'example'

    cloud_scraper_verify: bool = False
    # rss
    ## douyin
    rss_douyin_user_semaphore: int = 5
    rss_douyin_user_feeds_cache_time: int = 1800
    rss_douyin_user_auto_fetch_timeout: float = 60
    rss_douyin_user_auto_fetch_start_wait: float = 30
    rss_douyin_user_auto_fetch_enable: bool = False
    rss_douyin_user_auto_fetch_wait: int = 600
    rss_douyin_user_auto_fetch_once_wait: int = 10
    rss_douyin_user_history_storage: str = '~/.rssapi/rss.douyin.user.history'
    rss_douyin_user_headless: bool = True

    # meta
    model_config = SettingsConfigDict(env_file='.env', extra='ignore')
