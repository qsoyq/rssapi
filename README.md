# rssapi

`rssapi` is a Python RSS subscription/API service. It exposes FastAPI routes that turn multiple upstream sources into RSS-friendly endpoints, including GitHub, Reddit, Twitter/X, YouTube, Telegram, V2EX, NGA, and other feeds.

## Tech stack

- Python 3.10+
- FastAPI, Uvicorn, and Hypercorn
- Pydantic settings
- pytest for tests
- Ruff for linting and formatting
- uv for dependency and environment management

## Install

```bash
pip install git+https://github.com/qsoyq/rssapi.git
```

For local development:

```bash
uv venv
uv sync --all-groups
```

## Run locally

```bash
uv run rssapi-server
```

You can also run the FastAPI app through an ASGI server, for example:

```bash
uv run uvicorn rssapi.main:app --reload
```

## Test

```bash
uv run pytest tests/
```

The default test run is intended for CI and skips live upstream integration cases that require private credentials or stable third-party access, such as NGA credentialed requests, Reddit live subreddit fetches, and Loon plugin URLs that can be blocked by upstream anti-bot checks. Re-enable or run those cases locally only when the required credentials and network access are available.

## Lint and format

```bash
uv run ruff check .
uv run ruff format --check .
```

## Build

```bash
uv build
```

Build outputs are generated under `dist/` and should not be committed.

## Release process

1. Confirm all intended Issues are merged and CI is passing on `main`.
2. Update the package version in `pyproject.toml` when cutting a new release.
3. Run lint, format check, tests, and build locally or in CI.
4. Create a release tag and GitHub release notes.
5. Record notable release or rollback notes under `docs/release/` when needed.

## Branch and review workflow

- Use `main` as the default branch.
- Create feature/fix/tooling branches from `main` using `<type>/<issue-id>-<short-desc>`, for example `fix/123-cache-ttl`.
- Open a PR for changes and fill in the PR template.
- Keep PRs focused on their linked Issue.
- Use CODEOWNERS review for areas that need owner attention.

## Maintainer

- Owner: [`@qsoyq`](https://github.com/qsoyq)

## Related documentation

- [Contributing](CONTRIBUTING.md)
- [Security policy](SECURITY.md)
- [Decision records](docs/decisions/)
- [Release notes](docs/release/)
- [Postmortems](docs/postmortems/)

## Configuration

All configuration items support environment variable overrides. They can also be written to a local `.env` file in the project root. Do not commit `.env` files.

The sections below list environment variables for RSS sources and middleware.

### Cache configuration

Each data source can configure cache size (`*_MAXSIZE`, max entries) and expiry (`*_TTL`, seconds) independently.

#### Middleware (`RSS_MIDDLEWARE_`)

| Environment variable | Default | Description |
| --- | --- | --- |
| `RSS_MIDDLEWARE_CLEAR_HOME_PAGE_URL_ENABLED` | `true` | Whether to clear `home_page_url` from JSON Feeds; set to `false` (or `f`) to preserve each feed's homepage |

#### Twitter (`RSS_TWITTER_`)

| 环境变量 | 默认值 | 说明 |
| --- | --- | --- |
| `RSS_TWITTER_USER_POSTS_CACHE_TTL` | `14400` | 用户推文列表缓存 TTL |
| `RSS_TWITTER_USER_POSTS_CACHE_MAXSIZE` | `4096` | 用户推文列表缓存条目数 |
| `RSS_TWITTER_FEED_CACHE_TTL` | `3600` | Feed 缓存 TTL |
| `RSS_TWITTER_FEED_CACHE_MAXSIZE` | `4096` | Feed 缓存条目数 |

#### Reddit (`RSS_REDDIT_`)

| 环境变量 | 默认值 | 说明 |
| --- | --- | --- |
| `RSS_REDDIT_USER_POSTS_CACHE_TTL` | `600` | 用户帖子缓存 TTL |
| `RSS_REDDIT_USER_POSTS_CACHE_MAXSIZE` | `4096` | 用户帖子缓存条目数 |

#### GitHub (`RSS_GITHUB_`)

| 环境变量 | 默认值 | 说明 |
| --- | --- | --- |
| `RSS_GITHUB_RELEASE_CACHE_TTL` | `300` | Release 缓存 TTL |
| `RSS_GITHUB_RELEASE_CACHE_MAXSIZE` | `4096` | Release 缓存条目数 |
| `RSS_GITHUB_NOTIFICATION_CACHE_TTL` | `300` | Notification 缓存 TTL |
| `RSS_GITHUB_NOTIFICATION_CACHE_MAXSIZE` | `4096` | Notification 缓存条目数 |
| `RSS_GITHUB_COMMIT_CACHE_TTL` | `1800` | Commit 缓存 TTL |
| `RSS_GITHUB_COMMIT_CACHE_MAXSIZE` | `4096` | Commit 缓存条目数 |
| `RSS_GITHUB_ISSUE_CACHE_TTL` | `1800` | Issue 缓存 TTL |
| `RSS_GITHUB_ISSUE_CACHE_MAXSIZE` | `4096` | Issue 缓存条目数 |

#### V2fly (`RSS_V2FLY_`)

| 环境变量 | 默认值 | 说明 |
| --- | --- | --- |
| `RSS_V2FLY_GEOSITE_NAME_CACHE_TTL` | `43200` | Geosite name 缓存 TTL |
| `RSS_V2FLY_GEOSITE_NAME_CACHE_MAXSIZE` | `4096` | Geosite name 缓存条目数 |
| `RSS_V2FLY_GEOSITE_LIBRARY_CACHE_TTL` | `43200` | Geosite dlc.dat 缓存 TTL |
| `RSS_V2FLY_GEOSITE_LIBRARY_CACHE_MAXSIZE` | `16` | Geosite dlc.dat 缓存条目数 |

#### Gofans (`RSS_GOFANS_`)

| 环境变量 | 默认值 | 说明 |
| --- | --- | --- |
| `RSS_GOFANS_CACHE_TTL` | `3600` | Gofans 缓存 TTL |
| `RSS_GOFANS_CACHE_MAXSIZE` | `4096` | Gofans 缓存条目数 |

#### V2EX (`RSS_V2EX_`)

| 环境变量 | 默认值 | 说明 |
| --- | --- | --- |
| `RSS_V2EX_CACHE_TTL` | `600` | V2EX 缓存 TTL |
| `RSS_V2EX_CACHE_MAXSIZE` | `4096` | V2EX 缓存条目数 |

#### Loon (`RSS_LOON_`)

| 环境变量 | 默认值 | 说明 |
| --- | --- | --- |
| `RSS_LOON_CACHE_TTL` | `1800` | Loon 缓存 TTL |
| `RSS_LOON_CACHE_MAXSIZE` | `4096` | Loon 缓存条目数 |

#### Readhub (`RSS_READHUB_`)

| 环境变量 | 默认值 | 说明 |
| --- | --- | --- |
| `RSS_READHUB_CACHE_TTL` | `900` | Readhub 缓存 TTL |
| `RSS_READHUB_CACHE_MAXSIZE` | `4096` | Readhub 缓存条目数 |

#### Telegram (`RSS_TELEGRAM_`)

| 环境变量 | 默认值 | 说明 |
| --- | --- | --- |
| `RSS_TELEGRAM_CACHE_TTL` | `900` | Telegram 频道消息缓存 TTL |
| `RSS_TELEGRAM_CACHE_MAXSIZE` | `4096` | Telegram 频道消息缓存条目数 |
| `RSS_TELEGRAM_MEDIA_CACHE_TTL` | `300` | Telegram 媒体 CDN 地址缓存 TTL |
| `RSS_TELEGRAM_MEDIA_CACHE_MAXSIZE` | `4096` | Telegram 媒体缓存条目数 |
| `RSS_TELEGRAM_MEDIA_REQUEST_TIMEOUT` | `15` | Telegram 媒体 embed 请求超时（秒） |
| `RSS_TELEGRAM_MEDIA_RETRY_COUNT` | `1` | Telegram 媒体 embed 临时失败重试次数 |
| `RSS_TELEGRAM_MEDIA_BASE_URL` | `https://t.me` | Telegram embed 上游地址，主要用于测试或代理 |

#### 1024.day (`RSS_DAY1024_`)

| 环境变量 | 默认值 | 说明 |
| --- | --- | --- |
| `RSS_DAY1024_CACHE_TTL` | `3600` | 1024.day 缓存 TTL |
| `RSS_DAY1024_CACHE_MAXSIZE` | `4096` | 1024.day 缓存条目数 |

#### NGA (`RSS_NGA_`)

| 环境变量 | 默认值 | 说明 |
| --- | --- | --- |
| `RSS_NGA_CACHE_TTL` | `300` | 帖子列表缓存 TTL |
| `RSS_NGA_CACHE_MAXSIZE` | `4096` | 帖子列表缓存条目数 |
| `RSS_NGA_SECTIONS_CACHE_TTL` | `86400` | 分区信息缓存 TTL |
| `RSS_NGA_SECTIONS_CACHE_MAXSIZE` | `1024` | 分区信息缓存条目数 |
| `RSS_NGA_SMILES_CACHE_TTL` | `259200` | 表情缓存 TTL（默认 3 天） |
| `RSS_NGA_SMILES_CACHE_MAXSIZE` | `1024` | 表情缓存条目数 |
| `RSS_NGA_SMILES_PRELOAD_ENABLE` | `true` | 启动时是否后台预加载 NGA 表情；设为 `false` 可跳过 |
| `RSS_NGA_THREAD_DETAIL_CACHE_TTL` | `86400` | 帖子详情缓存 TTL |
| `RSS_NGA_THREAD_DETAIL_CACHE_MAXSIZE` | `4096` | 帖子详情缓存条目数 |

#### NodeSeek (`RSS_NODESEEK_`)

| 环境变量 | 默认值 | 说明 |
| --- | --- | --- |
| `RSS_NODESEEK_CACHE_TTL` | `600` | 分类列表缓存 TTL |
| `RSS_NODESEEK_CACHE_MAXSIZE` | `4096` | 分类列表缓存条目数 |
| `RSS_NODESEEK_ARTICLE_POST_CACHE_TTL` | `259200` | 文章正文缓存 TTL（默认 3 天） |
| `RSS_NODESEEK_ARTICLE_POST_CACHE_MAXSIZE` | `4096` | 文章正文缓存条目数 |
| `RSS_NODESEEK_LOGIN_REQUIRED_CACHE_TTL` | `259200` | 登录态判定缓存 TTL（默认 3 天） |
| `RSS_NODESEEK_LOGIN_REQUIRED_CACHE_MAXSIZE` | `4096` | 登录态判定缓存条目数 |

#### YouTube (`RSS_YOUTUBE_`)

| 环境变量 | 默认值 | 说明 |
| --- | --- | --- |
| `RSS_YOUTUBE_CHANNEL_FEED_CACHE_TTL` | `3600` | 频道 Feed 缓存 TTL |
| `RSS_YOUTUBE_CHANNEL_FEED_CACHE_MAXSIZE` | `4096` | 频道 Feed 缓存条目数 |

#### 抖音 (`RSS_DOUYIN_`)

| 环境变量 | 默认值 | 说明 |
| --- | --- | --- |
| `RSS_DOUYIN_USER_FEEDS_CACHE_TTL` | `1800` | 用户作品列表缓存 TTL |
| `RSS_DOUYIN_USER_FEEDS_CACHE_MAXSIZE` | `4096` | 用户作品列表缓存条目数 |
| `RSS_DOUYIN_TOPIC_FEEDS_CACHE_TTL` | `1800` | 话题作品缓存 TTL 基准值，实际随机 30–60 分钟 |
| `RSS_DOUYIN_TOPIC_FEEDS_CACHE_MAXSIZE` | `4096` | 话题作品缓存条目数，按 Cookie 和作品上限区分 |
| `RSS_DOUYIN_TOPIC_FETCH_CONCURRENCY` | `1` | 话题抓取并发上限，同时遵守全局 Playwright 容量限制 |

抖音用户作品和话题订阅支持 query 参数 `cookies` 或请求头 `X-Douyin-Cookie`，同时传入时请求头优先。
Cookie 使用完整字符串，最小已验证形式为 `sessionid_ss=<会话值>`。请求示例：

```bash
curl 'http://localhost:8000/api/rss/douyin/user/<用户主页ID>' \
  -H "X-Douyin-Cookie: $DOUYIN_COOKIE"
curl 'http://localhost:8000/api/rss/douyin/topic/示例话题?max_posts=30' \
  -H "X-Douyin-Cookie: $DOUYIN_COOKIE"
```

话题名可带 `#`，在 URL 路径中需要编码为 `%23`。仅保留明确带该话题的作品，按最新发布时间排列；
每页抓取 15 个搜索结果，最多三页，`max_posts` 默认 30、范围 1–45，过滤后可能不足该数量。
`timeout` 默认 60 秒，包括排队、浏览器初始化与分页；`use_cache=false` 可跳过 Feed 缓存。
返回格式为 JSON Feed。

旧地址 `/api/rss/douyin/user/<用户主页ID>/<sessionid_ss>` 保持兼容，始终使用路径凭据，query/header
不覆盖其 session ID。旧响应、条目 ID 和自动抓取历史保持原样；新入口的 `feed_url` 移除 `cookies`。

话题接口使用无头浏览器初始化登录态，再通过 HTTPX 直接请求搜索 API，无需操作搜索页。
初始化和搜索受限时返回 `503`，上游空响应或异常返回 `502`，超时返回 `504`，不会把验证失败缓存为空 Feed。
该路径依赖当前抖音请求校验策略（包括 `uifid` 与 `x-tt-argus`），策略变更时需更新适配。

### Playwright 容量配置

| 环境变量 | 默认值 | 说明 |
| --- | --- | --- |
| `RSS_PLAYWRIGHT_CONCURRENCY` | `11` | 单个 rssapi 进程可同时运行的 Chromium 浏览器上限；所有 Playwright 来源共享该额度 |
| `RSS_TIKTOK_PLAYWRIGHT_CONCURRENCY` | `1` | TikTok v2 的活跃 Chromium 上限 |
| `RSS_TIKTOK_PLAYWRIGHT_MAX_INFLIGHT` | `3` | TikTok v2 可同时接收的不同浏览器任务上限；超出时返回 `503` |
| `RSS_TIKTOK_PLAYWRIGHT_QUEUE_TIMEOUT` | `35` | TikTok v2 等待来源浏览器槽位的秒数；生产环境可缩短以快速返回 `503` |

> `RSS_PLAYWRIGHT_CONCURRENCY` 是进程级限制；多 worker 部署应按 worker 数分配总浏览器预算。

#### Instagram (`RSS_INSTAGRAM_`)

| 环境变量 | 默认值 | 说明 |
| --- | --- | --- |
| `RSS_INSTAGRAM_APP_ID` | `936619743392459` | Instagram 公开 Web App ID |
| `RSS_INSTAGRAM_GRAPHQL_DOC_ID` | `27128499623469141` | embed 缺失视频地址时，按 shortcode 查询单帖的 GraphQL 查询标识 |
| `RSS_INSTAGRAM_USER_POSTS_CACHE_TTL` | `10800` | 用户贴文列表缓存 TTL（随机 3–6 小时） |
| `RSS_INSTAGRAM_USER_POSTS_CACHE_MAXSIZE` | `4096` | 用户贴文列表缓存条目数 |

> 注：缓存配置在进程启动时读取，修改环境变量后需要重启服务才能生效。

Instagram、Telegram 和 Bilibili 的媒体字段使用稳定的 RSSAPI 地址；访问媒体地址时会重新解析上游资源并返回 `302`，响应带 `Cache-Control: no-store`。订阅内容只保存稳定媒体入口，不保存短期 CDN 签名地址；私有账号仍需在请求头中提供对应 Cookie。

Instagram 媒体路由优先解析单帖 embed。部分视频的 embed 因版权限制返回 `copyright_blocked: true` 并省略 `video_url`；视频地址缺失或无效时，服务会通过 `PolarisPostRootQuery` 按 shortcode 精确查询单帖，读取 `video_versions`，不查询或遍历用户 feed。匿名媒体解析结果沿用基准 TTL 为 60 秒的随机缓存（实际 60–120 秒）；带 Cookie 的请求不使用公共缓存。

`doc_id` 及查询方式参考 [mbedfx 的 Instagram 实现](https://github.com/shamu4life/mbedfx/blob/main/src/platforms/instagram/fetch.ts)，已于 2026-10-06 用帖子 `DeG_Vlzp2O7` 验证单帖查询及 MP4 CDN 可用。该值是 Instagram 内部 GraphQL 查询标识，不是帖子 ID 或 CDN 签名；上游更新可能使其失效，此时可通过 `RSS_INSTAGRAM_GRAPHQL_DOC_ID` 更新并重启服务。

#### 微博 (`RSS_WEIBO_`)

| 环境变量 | 默认值 | 说明 |
| --- | --- | --- |
| `RSS_WEIBO_MEDIA_CACHE_TTL` | `600` | 视频签名地址缓存 TTL（随机 1–2 倍，即 10–20 分钟）；必须远小于微博签名约 60 分钟的寿命 |
| `RSS_WEIBO_MEDIA_CACHE_MAXSIZE` | `4096` | 视频签名地址缓存条目数 |

> 微博视频 CDN 地址带 `Expires` + `ssig` 签名，寿命约 60 分钟。Feed 中的 `<video src>` 与
> `attachments[].url` 输出稳定地址 `/api/rss/weibo/media/{post_id}/{n}`；该端点在每次请求时
> 按帖子 id 重新向上游解析并返回 `302`，因此对任意历史帖子都长期可用。响应带
> `Cache-Control: no-store`，客户端不得缓存重定向结果。
