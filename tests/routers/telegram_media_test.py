from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from threading import Thread
from typing import Generator

import pytest
from fastapi import Request
from fastapi.testclient import TestClient

from rssapi.applications.telegram import router as telegram_router
from rssapi.applications.telegram.router import fetch_feeds
from rssapi.applications.telegram.schemas import TelegramChannalMessage
from rssapi.main import app


def _request() -> Request:
    return Request(
        {
            "type": "http",
            "scheme": "https",
            "server": ("rss.example", 443),
            "path": "/api/rss/telegram/channel",
            "query_string": b"channels=example",
            "headers": [],
        }
    )


async def _messages(_channel: str) -> list[TelegramChannalMessage]:
    return [
        TelegramChannalMessage(
            head="https://cdn.example/avatar.jpg",
            msgid="123",
            channelName="example",
            username="example",
            title="Photo",
            text="Photo",
            updated="2026-09-15T00:00:00Z",
            authorName=None,
            contentHtml="<div>Photo</div>",
            photoUrls=["https://cdn.example/photo.jpg"],
            tags=[],
        )
    ]


@pytest.mark.asyncio
async def test_telegram_feed_uses_stable_media_url(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr("rssapi.applications.telegram.router.get_channel_messages", _messages)

    items = await fetch_feeds(["example"], req=_request())

    assert len(items) == 1
    stable_url = "https://rss.example/api/rss/telegram/media/example/123/0"
    assert str(items[0].image) == stable_url
    assert stable_url in (items[0].content_html or "")


@pytest.fixture
def embed_server() -> Generator[ThreadingHTTPServer, None, None]:
    class Handler(BaseHTTPRequestHandler):
        requests = 0

        def do_GET(self):  # noqa: N802
            Handler.requests += 1
            if self.path.startswith("/botmzt/") and self.path.endswith("?embed=1"):
                message_id = self.path.split("/")[2].split("?")[0]
                if message_id == "999":
                    self.send_response(404)
                    self.end_headers()
                    return
                extra_photos = ""
                if message_id == "125":
                    extra_photos = "".join(
                        f'<a class="tgme_widget_message_photo_wrap" '
                        f"style=\"background-image:url('https://cdn5.telesco.pe/file/photo-{index}.jpg')\"></a>"
                        for index in range(2, 11)
                    )
                body = f"""<div class="tgme_widget_message js-widget_message" data-post="botmzt/{message_id}">
<a class="tgme_widget_message_photo_wrap" style="background-image:url('https://cdn5.telesco.pe/file/photo.jpg')"></a>
<video class="tgme_widget_message_video" src="https://cdn5.telesco.pe/file/video.mp4?token=fresh"></video>
{extra_photos}
 </div>""".encode()
                self.send_response(200)
                self.send_header("Content-Type", "text/html")
                self.send_header("Content-Length", str(len(body)))
                self.end_headers()
                self.wfile.write(body)
                return
            self.send_response(404)
            self.end_headers()

        def log_message(self, *_args):
            return

    server = ThreadingHTTPServer(("127.0.0.1", 0), Handler)
    thread = Thread(target=server.serve_forever, daemon=True)
    thread.start()
    yield server
    server.shutdown()
    thread.join(timeout=2)


def test_telegram_media_route_resolves_image_and_video_with_cache(embed_server: ThreadingHTTPServer) -> None:
    previous_base_url = telegram_router.settings.telegram.media_base_url
    telegram_router.settings.telegram.media_base_url = f"http://127.0.0.1:{embed_server.server_port}"
    try:
        with TestClient(app) as client:
            image = client.get("/api/rss/telegram/media/botmzt/123/0", follow_redirects=False)
            video = client.get("/api/rss/telegram/media/botmzt/123/1", follow_redirects=False)
    finally:
        telegram_router.settings.telegram.media_base_url = previous_base_url

    assert image.status_code == 302
    assert image.headers["location"] == "https://cdn5.telesco.pe/file/photo.jpg"
    assert image.headers["cache-control"] == "no-store"
    assert video.status_code == 302
    assert video.headers["location"].startswith("https://cdn5.telesco.pe/file/video.mp4?token=fresh")


def test_telegram_media_route_uses_message_cache(embed_server: ThreadingHTTPServer) -> None:
    previous_base_url = telegram_router.settings.telegram.media_base_url
    telegram_router.settings.telegram.media_base_url = f"http://127.0.0.1:{embed_server.server_port}"
    try:
        with TestClient(app) as client:
            first = client.get("/api/rss/telegram/media/botmzt/124/0", follow_redirects=False)
            second = client.get("/api/rss/telegram/media/botmzt/124/0", follow_redirects=False)
    finally:
        telegram_router.settings.telegram.media_base_url = previous_base_url

    assert first.status_code == second.status_code == 302
    assert getattr(embed_server.RequestHandlerClass, "requests") == 1


def test_telegram_media_route_reports_missing_message(embed_server: ThreadingHTTPServer) -> None:
    previous_base_url = telegram_router.settings.telegram.media_base_url
    telegram_router.settings.telegram.media_base_url = f"http://127.0.0.1:{embed_server.server_port}"
    try:
        with TestClient(app) as client:
            response = client.get("/api/rss/telegram/media/botmzt/999/0", follow_redirects=False)
    finally:
        telegram_router.settings.telegram.media_base_url = previous_base_url

    assert response.status_code == 404


def test_telegram_media_route_accepts_index_above_nine_and_checks_actual_length(
    embed_server: ThreadingHTTPServer,
) -> None:
    previous_base_url = telegram_router.settings.telegram.media_base_url
    telegram_router.settings.telegram.media_base_url = f"http://127.0.0.1:{embed_server.server_port}"
    try:
        with TestClient(app) as client:
            existing = client.get("/api/rss/telegram/media/botmzt/125/10", follow_redirects=False)
            missing = client.get("/api/rss/telegram/media/botmzt/125/11", follow_redirects=False)
            negative = client.get("/api/rss/telegram/media/botmzt/125/-1", follow_redirects=False)
    finally:
        telegram_router.settings.telegram.media_base_url = previous_base_url

    assert existing.status_code == 302
    assert existing.headers["location"] == "https://cdn5.telesco.pe/file/photo-10.jpg"
    assert missing.status_code == 404
    assert negative.status_code == 422
