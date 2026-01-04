from pydantic import BaseModel

import rssapi.applications.rss.schemas.notifications.apple as apple_
import rssapi.applications.rss.schemas.notifications.bark as bark_
import rssapi.applications.rss.schemas.notifications.gmail as gmail_
import rssapi.applications.rss.schemas.notifications.gotify as gotify_
import rssapi.applications.rss.schemas.notifications.telegram as telegram_


class PushMessage(BaseModel):
    telegram: telegram_.TelegramPushMessage | None = None
    gmail: gmail_.GmailPushMessage | None = None
    bark: bark_.BarkPushMessage | None = None


class PushMessageV3(BaseModel):
    telegram: telegram_.TelegramPushMessageV3 | None = None
    gmail: gmail_.GmailPushMessage | None = None
    bark: bark_.BarkPushMessage | None = None
    gotify: gotify_.GotifyPushMessage | None = None
    apple: apple_.ApplePushMessage | None = None


class PushMessages(BaseModel):
    messages: list[PushMessage]


class PushMessagesV3(BaseModel):
    messages: list[PushMessageV3]
