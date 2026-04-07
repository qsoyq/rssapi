from datetime import datetime
from typing import Literal, Optional

from pydantic import BaseModel, Field, field_validator


class TweetAuthor(BaseModel):
    id: str | None = None
    name: str
    screen_name: str = Field(alias="screenName")
    profile_image_url: str | None = Field(default=None, alias="profileImageUrl")
    verified: bool | None = None

    model_config = {"populate_by_name": True}


class TweetMetrics(BaseModel):
    likes: int = 0
    retweets: int = 0
    replies: int = 0
    quotes: int = 0
    views: int = 0
    bookmarks: int = 0


class TweetMedia(BaseModel):
    type: Literal["photo", "video", "animated_gif"]  # "photo" | "video" | "animated_gif"
    url: str
    width: Optional[int] = None
    height: Optional[int] = None


class QuotedTweet(BaseModel):
    id: str
    text: str
    author: TweetAuthor
    urls: list[str] = Field(default_factory=list)
    article_title: str | None = None


class Tweet(BaseModel):
    id: str
    text: str
    author: TweetAuthor
    metrics: TweetMetrics
    created_at: str = Field(alias="createdAt")
    media: list[TweetMedia] = Field(default_factory=list)
    urls: list[str] = Field(default_factory=list)
    is_retweet: bool = Field(default=False, alias="isRetweet")
    retweeted_by: str | None = Field(default=None, alias="retweetedBy")
    lang: str | None = None
    score: float | None = None
    quoted_tweet: QuotedTweet | None = Field(default=None, alias="quotedTweet")

    @field_validator("created_at", mode="before")
    @classmethod
    def normalize_created_at(cls, value: str) -> str:
        if not isinstance(value, str):
            return value
        try:
            return datetime.strptime(value, "%a %b %d %H:%M:%S %z %Y").isoformat()
        except ValueError:
            return value

    model_config = {"populate_by_name": True}
