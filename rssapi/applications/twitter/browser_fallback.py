import logging
import urllib.parse
from typing import Any, cast

from playwright.sync_api import TimeoutError as PlaywrightTimeoutError
from playwright.sync_api import sync_playwright

from rssapi.applications.twitter.types import Tweet
from rssapi.utils.playwright_capacity import (
    PlaywrightCapacityError,
    PlaywrightLease,
    acquire_playwright_slot,
)

logger = logging.getLogger(__file__)


class TwitterBrowserFallbackError(RuntimeError):
    """Raised when the browser fallback cannot produce Twitter posts."""

    def __init__(self, message: str, *, kind: str, status_code: int = 502):
        super().__init__(message)
        self.kind = kind
        self.status_code = status_code


def _latest_search_url(screen_name: str) -> str:
    query = urllib.parse.quote(f"from:{screen_name} -filter:replies")
    return f"https://x.com/search?q={query}&src=typed_query&f=live"


def _cookies_by_str(cookie_string: str, url: str) -> list[dict[str, str]]:
    cookies: list[dict[str, str]] = []
    for chunk in cookie_string.split(";"):
        name, sep, value = chunk.strip().partition("=")
        if sep:
            cookies.append({"name": name, "value": value, "url": url})
    return cookies


def _tweet_payloads_from_page(page, screen_name: str, max_tweets: int) -> list[dict[str, Any]]:
    return cast(
        list[dict[str, Any]],
        page.evaluate(
            """
        ({ screenName, maxTweets }) => {
          const normalizedScreenName = screenName.toLowerCase();
          const tweets = [];
          const seen = new Set();

          for (const article of document.querySelectorAll('article')) {
            const statusLinks = [...article.querySelectorAll('a[href*="/status/"]')]
              .map((anchor) => anchor.href)
              .filter((href) => /\\/status\\/\\d+/.test(href));
            const statusUrl = statusLinks[0];
            const statusMatch = statusUrl && statusUrl.match(/x\\.com\\/([^/]+)\\/status\\/(\\d+)/);
            if (!statusMatch) {
              continue;
            }

            const authorScreenName = statusMatch[1];
            const id = statusMatch[2];
            if (seen.has(id)) {
              continue;
            }
            seen.add(id);

            const userNameNode = article.querySelector('[data-testid="User-Name"]');
            const authorName =
              userNameNode?.querySelector('div[dir="ltr"] span')?.textContent?.trim()
              || authorScreenName;
            const text = [...article.querySelectorAll('[data-testid="tweetText"]')]
              .map((node) => node.innerText.trim())
              .filter(Boolean)
              .join("\\n");
            const createdAt = article.querySelector('time')?.getAttribute('datetime') || new Date().toISOString();
            const avatar = article.querySelector('img[src*="profile_images"]')?.src || null;
            const media = [...article.querySelectorAll('img[src]')]
              .map((img) => ({
                type: "photo",
                url: img.src,
                width: img.naturalWidth || undefined,
                height: img.naturalHeight || undefined,
              }))
              .filter((item) => item.url.includes('pbs.twimg.com/media/'));
            const isRetweet = authorScreenName.toLowerCase() !== normalizedScreenName;

            tweets.push({
              id,
              text,
              author: {
                name: authorName,
                screenName: authorScreenName,
                profileImageUrl: avatar,
              },
              metrics: {},
              createdAt,
              media,
              urls: [],
              isRetweet,
              retweetedBy: isRetweet ? screenName : null,
            });

            if (tweets.length >= maxTweets) {
              break;
            }
          }

          return tweets;
        }
        """,
            {"screenName": screen_name, "maxTweets": max_tweets},
        ),
    )


def _tweet_payloads_from_url(context, url: str, screen_name: str, max_tweets: int, label: str) -> list[dict[str, Any]]:
    page = context.new_page()
    try:
        page.goto(url, wait_until="domcontentloaded", timeout=30_000)
        attempts = max(4, min(12, max_tweets))

        payloads: list[dict[str, Any]] = []
        for _ in range(attempts):
            try:
                page.wait_for_selector("article", timeout=3_000)
            except PlaywrightTimeoutError:
                logger.debug(f"Twitter browser fallback did not find articles yet: {label} {url}")

            payloads = _tweet_payloads_from_page(page, screen_name, max_tweets)
            if len(payloads) >= max_tweets:
                break
            page.mouse.wheel(0, 1600)
            page.wait_for_timeout(1_000)

        logger.info(f"Twitter browser fallback candidate fetched {len(payloads)} rendered tweets: {label}")
        return payloads
    finally:
        page.close()


def fetch_user_posts_with_browser(screen_name: str, max_tweets: int, cookie_string: str) -> list[Tweet]:
    logger.info(
        f"Fetching Twitter user posts with browser fallback: screen_name={screen_name} max_tweets={max_tweets}"
    )
    payloads: list[dict[str, Any]] = []
    candidates = [
        ("authenticated search", _latest_search_url(screen_name), cookie_string),
        ("authenticated profile", f"https://x.com/{screen_name}", cookie_string),
        ("public profile", f"https://x.com/{screen_name}", ""),
    ]

    lease: PlaywrightLease | None = None
    try:
        lease = acquire_playwright_slot("twitter_browser_fallback")
        with sync_playwright() as playwright:
            try:
                browser = playwright.chromium.launch(headless=True)
            except Exception as exc:
                raise TwitterBrowserFallbackError(
                    "Twitter browser fallback could not launch Chromium",
                    kind="startup",
                    status_code=503,
                ) from exc

            try:
                for label, url, candidate_cookies in candidates:
                    if label.startswith("authenticated") and not candidate_cookies:
                        continue

                    context = browser.new_context()
                    try:
                        if candidate_cookies:
                            context.add_cookies(cast(Any, _cookies_by_str(candidate_cookies, "https://x.com")))
                        payloads = _tweet_payloads_from_url(context, url, screen_name, max_tweets, label)
                        if payloads:
                            logger.info(f"Twitter browser fallback selected candidate: {label}")
                            break
                    finally:
                        context.close()

                    if payloads:
                        break
            except TwitterBrowserFallbackError:
                raise
            except PlaywrightTimeoutError as exc:
                raise TwitterBrowserFallbackError(
                    "Twitter browser fallback timed out while rendering the profile",
                    kind="timeout",
                    status_code=502,
                ) from exc
            except Exception as exc:
                raise TwitterBrowserFallbackError(
                    "Twitter browser fallback failed while rendering the profile",
                    kind="rendering",
                    status_code=502,
                ) from exc
            finally:
                browser.close()
    except PlaywrightCapacityError as exc:
        raise TwitterBrowserFallbackError(
            "Twitter browser fallback is busy",
            kind="busy",
            status_code=503,
        ) from exc
    except TwitterBrowserFallbackError:
        raise
    except Exception as exc:
        raise TwitterBrowserFallbackError(
            "Twitter browser fallback could not start Playwright",
            kind="startup",
            status_code=503,
        ) from exc
    finally:
        if lease is not None:
            lease.release()

    tweets = [Tweet.model_validate(payload) for payload in payloads[:max_tweets]]
    if not tweets:
        raise TwitterBrowserFallbackError(
            f"Twitter browser fallback returned no posts for {screen_name}",
            kind="no_results",
            status_code=502,
        )
    logger.info(f"Twitter browser fallback fetched {len(tweets)} rendered tweets for {screen_name}")
    return tweets
