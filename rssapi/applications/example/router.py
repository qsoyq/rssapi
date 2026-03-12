import logging

from fastapi import APIRouter, Request

from rssapi.applications.rss.schemas.rss.jsonfeed import JSONFeed, JSONFeedItem
from rssapi.core.responses import PrettyJSONFeedResponse

router = APIRouter(tags=["RSS"], prefix="/rss")

logger = logging.getLogger(__file__)

content_html = """
<div id="expanded" class="style-scope ytd-text-inline-expander"><yt-attributed-string user-input="" class="style-scope ytd-text-inline-expander"><span class="yt-core-attributed-string yt-core-attributed-string--white-space-pre-wrap" dir="auto"><span class="yt-core-attributed-string--link-inherit-color" dir="auto" style="color: rgb(19, 19, 19);">THE FIRST TAKE is a YouTube Channel dedicated to filming musicians and singers performing in a single take.

Episode 552 welcomes the six-member group IVE, consisting of YUJIN, GAEUL, REI, WONYOUNG, LIZ, and LEESEO, making their first appearance on THE FIRST TAKE.
Having swept numerous rookie awards at various music ceremonies, they will perform "After LIKE," which has ranked number one on all major Korean music charts.
This song has also charted on the U.S. Billboard Global 200 for 17 weeks, demonstrating its high popularity not only in Korea but worldwide.
Enjoy a special one-take performance exclusively for THE FIRST TAKE.

STREAMING &amp; DOWNLOAD：</span><span class="yt-core-attributed-string--link-inherit-color" dir="auto" style="color: rgb(6, 95, 212);"><a class="yt-core-attributed-string__link yt-core-attributed-string__link--call-to-action-color" tabindex="0" href="https://www.youtube.com/redirect?event=video_description&amp;redir_token=QUFFLUhqbmNYUmNFTUMta0tpaU1xZGNBcGIzV3hkOEhDQXxBQ3Jtc0tuNWVEUndpRzAwUHZ1ZHlCVnNiWXBnOW9aNlRXSE5VanNocW1VOVpzOURRblR3bm9RZkpoUnFXN2dJR3A5R2NDaXZ3SEJ1a3pmM3REdzIxakF5ZWwzWnVoUUhzSnFnVEpFT09QSjlkVmg5MEdfcnhjYw&amp;q=https%3A%2F%2Flnk.to%2FQJgcyzJX&amp;v=BiTEQGmPRfQ" rel="nofollow" target="_blank" force-new-state="true">https://lnk.to/QJgcyzJX</a></span></span></yt-attributed-string></div>
"""


@router.get(
    "/jsonfeed/example", response_model=JSONFeed, summary="JSONFeed 示例", response_class=PrettyJSONFeedResponse
)
async def jsonfeed(
    req: Request,
):
    """jsonfeed example"""

    host = req.url.hostname
    items: list[JSONFeedItem] = []
    feed = {
        "version": "https://jsonfeed.org/version/1",
        "title": "YouTube",
        "description": "YouTube",
        "home_page_url": "https://www.youtube.com",
        "feed_url": f"{req.url.scheme}://{host}{req.url.path}?{req.url.query}",
        "icon": "https://fastly.jsdelivr.net/gh/Koolson/Qure@master/IconSet/Color/YouTube.png",
        "favicon": "https://fastly.jsdelivr.net/gh/Koolson/Qure@master/IconSet/Color/YouTube.png",
        "items": items,
    }

    payload = {
        "author": {
            "url": "https://www.youtube.com/@The_FirstTake",
            "name": "The_FirstTake",
            "avatar": "https://yt3.googleusercontent.com/HqKlAwVvfGeRo6NJ7wZHoE20Ov6640WHw17sF8mhJe6bPNp0e78-3c546VevqnjAbAY6w9Sw=s160-c-k-c0x00ffffff-no-rj",
        },
        "url": "https://www.youtube.com/watch?v=BiTEQGmPRfQ",
        "title": "IVE - After LIKE / THE FIRST TAKE",
        "id": "BiTEQGmPRfQ",
        "date_published": "2025-08-08 06:00:00 CST",
        "content_html": content_html,
    }
    items.append(JSONFeedItem.model_validate(payload))
    return feed
