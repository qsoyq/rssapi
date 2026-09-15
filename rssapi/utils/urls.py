from urllib.parse import urlencode

from fastapi import Request

from rssapi.core.settings import settings


def public_url(req: Request, path: str) -> str:
    """Build a public URL using the inbound Host and configured public scheme."""
    host = req.headers.get("host") or req.url.netloc
    normalized_path = path if path.startswith("/") else f"/{path}"
    return f"{settings.public_url.scheme}://{host}{normalized_path}"


def public_request_url(req: Request, *, remove_query_params: set[str] | None = None) -> str:
    excluded = remove_query_params or set()
    query = urlencode([(key, value) for key, value in req.query_params.multi_items() if key not in excluded])
    path = req.url.path
    if query:
        path = f"{path}?{query}"
    return public_url(req, path)
