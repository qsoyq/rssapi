# rssapi

## Install

```bash
pip install git+https://github.com/qsoyq/rssapi.git
```

## Test

```bash
uv venv
uv run pytest tests/
```

## Configuration

所有配置项支持通过环境变量覆盖（也可写入项目根目录的 `.env` 文件）。下面列出当前各 RSS 源的缓存相关环境变量。

### 缓存配置

每个数据源的缓存大小（`*_MAXSIZE`，条目数上限）和过期时间（`*_TTL`，单位秒）均可独立配置。

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
