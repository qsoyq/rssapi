from rssapi.core.settings import settings


def render_collapsible_body(content_html: str) -> str:
    """Wrap rendered body HTML only when the global body-collapse setting is enabled."""
    if not content_html or not settings.rss_collapse_body_enabled:
        return content_html
    return f"<details><summary>查看正文</summary>{content_html}</details>"
