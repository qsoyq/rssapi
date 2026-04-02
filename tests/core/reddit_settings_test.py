from unittest.mock import patch

from rssapi.core.settings import RedditSettings


class TestRedditSettings:
    def test_default_dash_proxy_host(self):
        s = RedditSettings()
        assert s.dash_proxy_host == "https://p.19940731.xyz"

    @patch.dict("os.environ", {"RSS_REDDIT_DASH_PROXY_HOST": "https://custom.example.com"})
    def test_dash_proxy_host_from_env(self):
        s = RedditSettings()
        assert s.dash_proxy_host == "https://custom.example.com"
