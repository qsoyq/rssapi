from typing import Literal

from pydantic import BaseModel, Field

from rssapi.applications.rss.schemas.adapter import HttpUrl


class TelegramMedia(BaseModel):
    kind: Literal["image", "video"]
    url: HttpUrl
    mime_type: str


class TelegramChannalMessage(BaseModel):
    head: str | None = Field(None)
    msgid: str
    channelName: str
    username: str
    title: str
    text: str
    updated: str
    authorName: str | None = Field(None)
    contentHtml: str | None = Field(None)
    photoUrls: list[HttpUrl] | None = None
    videoUrls: list[HttpUrl] | None = None
    media: list[TelegramMedia] = Field(default_factory=list)
    tags: list[str] = Field(default_factory=list)
