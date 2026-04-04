from typing import Protocol, cast

from bs4 import BeautifulSoup as Soup
from bs4 import Tag


class MediaTitleDetector(Protocol):
    def __call__(self, document: Soup) -> bool: ...


def has_audio_video(document: Soup) -> bool:
    for video in document.find_all("video"):
        video = cast(Tag, video)
        if is_audio_video(video):
            return True
    return False


def has_video(document: Soup) -> bool:
    if document.find("iframe") is not None:
        return True

    for video in document.find_all("video"):
        video = cast(Tag, video)
        if is_gif_video(video) or is_audio_video(video):
            continue
        return True
    return False


def has_gallery(document: Soup) -> bool:
    images = [cast(Tag, img) for img in document.find_all("img")]
    content_images = [img for img in images if not is_nga_smile_image(img)]
    non_gif_images = [img for img in content_images if not is_gif_image(img)]
    return len(non_gif_images) > 1


def has_gif(document: Soup) -> bool:
    for video in document.find_all("video"):
        if is_gif_video(cast(Tag, video)):
            return True

    for image in document.find_all("img"):
        if is_gif_image(cast(Tag, image)):
            return True
    return False


def has_preview_image(document: Soup) -> bool:
    images = [cast(Tag, img) for img in document.find_all("img")]
    images = [img for img in images if not is_nga_smile_image(img)]
    return len(images) == 1 and not is_gif_image(images[0])


def is_gif_video(video: Tag) -> bool:
    return all(video.has_attr(attr) for attr in ("autoplay", "loop", "muted"))


def is_audio_video(video: Tag) -> bool:
    src = (video.get("src") or "").strip()
    return "/api/convert/dash/mp4" in src or "dash_url=" in src


def is_gif_image(image: Tag) -> bool:
    src = (image.get("src") or "").strip().lower()
    return ".gif" in src


def is_nga_smile_image(image: Tag) -> bool:
    src = (image.get("src") or "").strip().lower()
    return "/ngabbs/post/smile/" in src


MEDIA_TITLE_RULES: dict[str, MediaTitleDetector] = {
    "🔊": has_audio_video,
    "▶️": has_video,
    "📸": has_gallery,
    "🎞️": has_gif,
    "🖼️": has_preview_image,
}
