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

The sections below list cache-related environment variables for each RSS source.

### Cache configuration

Each data source can configure cache size (`*_MAXSIZE`, max entries) and expiry (`*_TTL`, seconds) independently.

#### Twitter (`RSS_TWITTER_`)

| 环境变量 | 默认值 | 说明 |
| --- | --- | --- |
| `RSS_TWITTER_USER_POSTS_CACHE_TTL` | `7200` | 用户推文列表缓存 TTL |
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

> 注：缓存配置在进程启动时读取，修改环境变量后需要重启服务才能生效。
