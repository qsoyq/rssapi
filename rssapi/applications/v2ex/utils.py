import logging
from dataclasses import dataclass
from typing import cast

import httpx
from bs4 import BeautifulSoup
from bs4 import BeautifulSoup as Soup
from dateutil import parser
from pydantic import BaseModel, Field

logger = logging.getLogger(__file__)


def get_url_from_notification_text(text: str) -> str | None:
    document = Soup(text, "lxml")
    for tag in document.select("a"):
        href = tag.get("href")
        if isinstance(href, str):
            if href.startswith("/t/"):
                return f"https://www.v2ex.com{href}"
            elif href.startswith("/solana/tips"):
                return f"https://www.v2ex.com{href}"
    return None


def get_title_from_notification_text(text: str) -> str:
    type_ = ""
    if "感谢了你在主题" in text:
        type_ = "感谢"
    elif "在回复" in text:
        type_ = "回复"
    document = Soup(text, "lxml")
    for tag in document.select("a"):
        href = tag.get("href")
        if isinstance(href, str) and href.startswith("/t/"):
            return f"{type_} - {tag.text}"
    return cast(str, Soup(text, "lxml").text)


class Topic(BaseModel):
    id: str
    title: str
    last_touched: int
    lastTouchedStr: str = Field(..., description="最后回复时间, 日期字符串, 如 2024-04-27 05:00:42 +08:00")


class GetTopicsRes(BaseModel):
    topics: list[Topic]
    has_next_page: bool = Field(..., description="是否还有下一页")


@dataclass
class GetTopicsData:
    topics: list[Topic]
    has_next_page: bool


def get_topics(session_key: str, page: int = 1) -> GetTopicsData:
    topics = []
    url = "https://www.v2ex.com/my/topics"
    res = httpx.get(url, params={"p": page}, cookies={"A2": session_key})
    res.raise_for_status()
    soup = BeautifulSoup(res.text, features="lxml")
    items = soup.find_all("div", class_="cell item")
    ele = soup.select_one('td[title="Next Page"]')
    has_next_page = True if ele and "disable_now" not in ele.attrs.get("class", []) else False

    for item in items:
        link = item.find("a", class_="topic-link")  # type:ignore
        title = link.text  # type:ignore
        tid = link.attrs["id"].split("-")[-1]  # type:ignore
        lastTouchedStr = item.find("span", class_="topic_info").find("span").attrs["title"]  # type:ignore
        if isinstance(lastTouchedStr, str):
            last_touched = int(parser.parse(lastTouchedStr).timestamp())
        else:
            logger.warning(f"skip becase invalid lastTouchedStr, item: {item}")
            continue
        topics.append(Topic(id=tid, title=title, lastTouchedStr=lastTouchedStr, last_touched=last_touched))
    return GetTopicsData(topics=topics, has_next_page=has_next_page)
