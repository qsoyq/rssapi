"""Pydantic models for Reddit API responses.

Based on real API data from r/aiyu subreddit.
"""

from __future__ import annotations

from pydantic import BaseModel, Field

# ── get_subreddit_about ─────────────────────────────────────────


class CommentContributionSettings(BaseModel):
    """评论区允许的媒体类型配置"""

    allowed_media_types: list[str] | None = None  # 允许的媒体类型, e.g. ["giphy", "static", "animated"]


class SubredditAbout(BaseModel):
    """get_subreddit_about 返回的 subreddit 详细信息 (已剥离外层 data)"""

    # ── 基础标识 ──
    id: str | None = None  # subreddit 短 id, e.g. "2ti81"
    name: str | None = None  # fullname, e.g. "t5_2ti81"
    display_name: str | None = None  # 显示名, e.g. "aiyu"
    display_name_prefixed: str | None = None  # 带前缀的显示名, e.g. "r/aiyu"
    title: str | None = None  # subreddit 标题, e.g. "All About IU (아이유) | /r/aiyu"
    url: str | None = None  # subreddit 路径, e.g. "/r/aiyu/"
    lang: str | None = None  # 语言, e.g. "en"
    subreddit_type: str | None = None  # 类型: public / private / restricted

    # ── 描述 ──
    public_description: str | None = None  # 公开简短描述 (纯文本)
    public_description_html: str | None = None  # 公开描述 (HTML)
    description: str | None = None  # 侧边栏详细描述 (Markdown)
    description_html: str | None = None  # 侧边栏详细描述 (HTML)
    submit_text: str | None = None  # 发帖页面提示文字
    submit_text_html: str | None = None  # 发帖提示 (HTML)
    header_title: str | None = None  # 页头标题/tooltip

    # ── 统计 ──
    subscribers: int | None = None  # 订阅者数量
    accounts_active: int | None = None  # 当前在线人数
    videostream_links_count: int | None = None  # 视频流链接数
    comment_score_hide_mins: int | None = None  # 隐藏评论分数的分钟数

    # ── 时间 ──
    created: float | None = None  # 创建时间 (Unix timestamp)
    created_utc: float | None = None  # 创建时间 (UTC Unix timestamp)

    # ── 图片/样式 ──
    icon_img: str | None = None  # subreddit 图标 URL
    icon_size: list[int] | None = None  # 图标尺寸 [width, height]
    header_img: str | None = None  # 页头图片 URL
    header_size: list[int] | None = None  # 页头图片尺寸 [width, height]
    banner_img: str | None = None  # banner 图片 URL
    banner_size: list[int] | None = None  # banner 尺寸 [width, height]
    banner_background_image: str | None = None  # banner 背景图 URL (高清)
    banner_background_color: str | None = None  # banner 背景色, e.g. "#9b9ac6"
    mobile_banner_image: str | None = None  # 移动端 banner URL
    community_icon: str | None = None  # 社区图标 URL (带样式)
    primary_color: str | None = None  # 主色调, e.g. "#9b9ac6"
    key_color: str | None = None  # 关键色, e.g. "#7e53c1"

    # ── 内容设置 ──
    submission_type: str | None = None  # 允许的帖子类型: any / link / self
    over18: bool | None = None  # 是否 NSFW
    quarantine: bool | None = None  # 是否被隔离
    spoilers_enabled: bool | None = None  # 是否允许剧透标记
    original_content_tag_enabled: bool | None = None  # 是否启用原创内容标签
    all_original_content: bool | None = None  # 是否全部为原创内容
    restrict_posting: bool | None = None  # 是否限制发帖
    restrict_commenting: bool | None = None  # 是否限制评论

    # ── 媒体设置 ──
    allow_images: bool | None = None  # 是否允许图片帖
    allow_videos: bool | None = None  # 是否允许视频帖
    allow_videogifs: bool | None = None  # 是否允许视频 GIF
    allow_galleries: bool | None = None  # 是否允许图库帖
    allow_polls: bool | None = None  # 是否允许投票帖
    allow_talks: bool | None = None  # 是否允许 Talk (音频直播)
    allow_predictions: bool | None = None  # 是否允许预测
    allow_prediction_contributors: bool | None = None  # 是否允许预测贡献者
    allow_predictions_tournament: bool | None = None  # 是否允许预测锦标赛
    show_media: bool | None = None  # 是否在列表中展示媒体
    show_media_preview: bool | None = None  # 是否展示媒体预览
    should_show_media_in_comments_setting: bool | None = None  # 评论区是否展示媒体

    allowed_media_in_comments: list[str] | None = None  # 评论区允许的媒体类型
    comment_contribution_settings: CommentContributionSettings | None = None  # 评论贡献设置

    # ── 外观/Flair 设置 ──
    link_flair_enabled: bool | None = None  # 帖子 flair 是否启用
    link_flair_position: str | None = None  # 帖子 flair 位置: left / right
    user_flair_enabled_in_sr: bool | None = None  # 用户 flair 是否在此 sr 启用
    user_flair_position: str | None = None  # 用户 flair 位置: left / right
    user_flair_type: str | None = None  # 用户 flair 类型: text / richtext
    can_assign_user_flair: bool | None = None  # 是否可以分配用户 flair
    can_assign_link_flair: bool | None = None  # 是否可以分配帖子 flair

    # ── 当前用户状态 (未登录时通常为 null) ──
    user_is_banned: bool | None = None  # 当前用户是否被封禁
    user_is_muted: bool | None = None  # 当前用户是否被禁言
    user_is_subscriber: bool | None = None  # 当前用户是否已订阅
    user_is_moderator: bool | None = None  # 当前用户是否为版主
    user_is_contributor: bool | None = None  # 当前用户是否为贡献者
    user_has_favorited: bool | None = None  # 当前用户是否收藏
    user_can_flair_in_sr: bool | None = None  # 当前用户能否在此 sr 设置 flair
    user_sr_flair_enabled: bool | None = None  # 当前用户 sr flair 是否启用
    user_sr_theme_enabled: bool | None = None  # 当前用户 sr 主题是否启用
    user_flair_background_color: str | None = None  # 当前用户 flair 背景色
    user_flair_text: str | None = None  # 当前用户 flair 文字
    user_flair_text_color: str | None = None  # 当前用户 flair 文字颜色
    user_flair_css_class: str | None = None  # 当前用户 flair CSS 类名
    user_flair_template_id: str | None = None  # 当前用户 flair 模板 ID
    user_flair_richtext: list[dict] | None = None  # 当前用户 flair 富文本

    # ── 杂项 ──
    wiki_enabled: bool | None = None  # 是否启用 wiki
    hide_ads: bool | None = None  # 是否隐藏广告
    emojis_enabled: bool | None = None  # 是否启用 emoji
    emojis_custom_size: list[int] | None = None  # 自定义 emoji 尺寸
    advertiser_category: str | None = None  # 广告分类
    public_traffic: bool | None = None  # 流量统计是否公开
    collapse_deleted_comments: bool | None = None  # 是否折叠已删评论
    is_crosspostable_subreddit: bool | None = None  # 是否允许跨帖
    has_menu_widget: bool | None = None  # 是否有菜单组件
    is_enrolled_in_new_modmail: bool | None = None  # 是否启用新版 modmail
    free_form_reports: bool | None = None  # 是否允许自由格式举报
    allow_discovery: bool | None = None  # 是否允许被发现/推荐
    accept_followers: bool | None = None  # 是否接受关注者
    disable_contributor_requests: bool | None = None  # 是否禁用贡献者请求
    should_archive_posts: bool | None = None  # 是否自动归档帖子
    community_reviewed: bool | None = None  # 社区是否已审核
    suggested_comment_sort: str | None = None  # 建议的评论排序方式
    notification_level: str | None = None  # 通知级别
    submit_link_label: str | None = None  # 提交链接按钮文字
    submit_text_label: str | None = None  # 提交文字帖按钮文字
    wls: int | None = None  # 白名单状态 (广告安全等级, 0-6)
    prediction_leaderboard_entry_type: int | None = None  # 预测排行榜条目类型

    model_config = {"extra": "allow"}


# ── get_subreddit (Listing 结构) ────────────────────────────────


class MediaSource(BaseModel):
    """图片/媒体的具体源信息"""

    y: int | None = None  # 高度 (px)
    x: int | None = None  # 宽度 (px)
    u: str | None = None  # 图片 URL
    gif: str | None = None  # GIF URL (动图时)


class MediaMetadataItem(BaseModel):
    """gallery 帖中单个媒体项的元数据"""

    status: str | None = None  # 状态, e.g. "valid"
    e: str | None = None  # 媒体类型, e.g. "Image"
    m: str | None = None  # MIME 类型, e.g. "image/jpg"
    p: list[MediaSource] | None = None  # 预览图列表 (不同分辨率)
    s: MediaSource | None = None  # 原始尺寸源
    id: str | None = None  # 媒体 ID


class GalleryItem(BaseModel):
    """gallery 帖中的单个项目引用"""

    media_id: str | None = None  # 对应 media_metadata 的 key
    is_deleted: bool | None = None  # 是否已删除
    id: int | None = None  # 项目 ID


class GalleryData(BaseModel):
    """gallery 帖的画廊数据"""

    items: list[GalleryItem] | None = None  # 画廊项目列表 (有序)


class PreviewImageSource(BaseModel):
    """预览图源信息"""

    url: str | None = None  # 图片 URL
    width: int | None = None  # 宽度 (px)
    height: int | None = None  # 高度 (px)


class PreviewImage(BaseModel):
    """预览图 (含原图和多尺寸缩略图)"""

    source: PreviewImageSource | None = None  # 原始尺寸
    resolutions: list[PreviewImageSource] | None = None  # 各分辨率版本
    id: str | None = None  # 预览图 ID


class Preview(BaseModel):
    """帖子的预览数据"""

    images: list[PreviewImage] | None = None  # 预览图列表
    enabled: bool | None = None  # 是否启用预览


class AuthorFlairRichtext(BaseModel):
    """作者 flair 富文本片段"""

    e: str | None = None  # 元素类型, e.g. "text", "emoji"
    t: str | None = None  # 文本内容


class PostData(BaseModel):
    """get_subreddit listing 中每个帖子的 data 部分"""

    # ── 帖子标识 ──
    id: str | None = None  # 帖子短 id, e.g. "1s88ljl"
    name: str | None = None  # fullname, e.g. "t3_1s88ljl"
    subreddit: str | None = None  # 所属 subreddit 名称
    subreddit_name_prefixed: str | None = None  # e.g. "r/aiyu"
    subreddit_id: str | None = None  # subreddit fullname, e.g. "t5_2ti81"
    subreddit_type: str | None = None  # subreddit 类型: public / private
    subreddit_subscribers: int | None = None  # 该 subreddit 的订阅者数
    domain: str | None = None  # 链接域名, e.g. "reddit.com", "imgur.com"

    # ── 帖子内容 ──
    title: str | None = None  # 帖子标题
    selftext: str | None = None  # 自帖内容 (Markdown)
    selftext_html: str | None = None  # 自帖内容 (HTML)
    url: str | None = None  # 帖子链接 (外链或 reddit 内链)
    url_overridden_by_dest: str | None = None  # 被覆盖的目标 URL (如 gallery URL)
    permalink: str | None = None  # 帖子 Reddit 永久链接路径
    thumbnail: str | None = None  # 缩略图 URL
    thumbnail_width: int | None = None  # 缩略图宽度
    thumbnail_height: int | None = None  # 缩略图高度

    # ── 作者 ──
    author: str | None = None  # 作者用户名
    author_fullname: str | None = None  # 作者 fullname, e.g. "t2_xxx"
    author_premium: bool | None = None  # 作者是否 Premium 会员
    author_is_blocked: bool | None = None  # 当前用户是否拉黑了该作者
    author_patreon_flair: bool | None = None  # 作者是否有 Patreon flair
    author_flair_text: str | None = None  # 作者 flair 文字
    author_flair_text_color: str | None = None  # 作者 flair 文字颜色
    author_flair_type: str | None = None  # 作者 flair 类型: text / richtext
    author_flair_css_class: str | None = None  # 作者 flair CSS 类
    author_flair_background_color: str | None = None  # 作者 flair 背景色
    author_flair_template_id: str | None = None  # 作者 flair 模板 ID
    author_flair_richtext: list[AuthorFlairRichtext] | None = None  # 作者 flair 富文本

    # ── 投票/统计 ──
    score: int | None = None  # 得分 (upvotes - downvotes)
    ups: int | None = None  # 赞数
    downs: int | None = None  # 踩数
    upvote_ratio: float | None = None  # 赞踩比, e.g. 0.99
    num_comments: int | None = None  # 评论数
    num_crossposts: int | None = None  # 跨帖数
    num_reports: int | None = None  # 举报数
    view_count: int | None = None  # 浏览数 (通常为 null)
    gilded: int | None = None  # 被 gild 次数
    total_awards_received: int | None = None  # 获得的奖章总数
    all_awardings: list[dict] | None = None  # 所有奖章详情
    awarders: list[dict] | None = None  # 颁奖者列表
    gildings: dict | None = None  # gild 详情

    # ── 帖子类型标记 ──
    is_self: bool | None = None  # 是否为自帖 (文字帖)
    is_gallery: bool | None = None  # 是否为图库帖
    is_video: bool | None = None  # 是否为视频帖
    is_meta: bool | None = None  # 是否为 meta 帖
    is_original_content: bool | None = None  # 是否为原创内容
    is_reddit_media_domain: bool | None = None  # 链接是否为 reddit 媒体域名
    is_crosspostable: bool | None = None  # 是否可以跨帖
    is_robot_indexable: bool | None = None  # 搜索引擎是否可索引
    is_created_from_ads_ui: bool | None = None  # 是否从广告界面创建
    over_18: bool | None = Field(default=None, alias="over_18")  # 是否 NSFW

    # ── 帖子状态 ──
    saved: bool | None = None  # 当前用户是否收藏
    hidden: bool | None = None  # 当前用户是否隐藏
    clicked: bool | None = None  # 当前用户是否点击过
    visited: bool | None = None  # 当前用户是否访问过
    archived: bool | None = None  # 是否已归档
    locked: bool | None = None  # 是否已锁定
    pinned: bool | None = None  # 是否被置顶 (个人主页)
    stickied: bool | None = None  # 是否被置顶 (subreddit)
    spoiler: bool | None = None  # 是否标记为剧透
    edited: bool | float | None = None  # 是否编辑过 (false 或编辑时间戳)
    contest_mode: bool | None = None  # 是否竞赛模式
    hide_score: bool | None = None  # 是否隐藏分数
    no_follow: bool | None = None  # 链接是否 nofollow
    send_replies: bool | None = None  # 是否发送回复通知
    likes: bool | None = None  # 当前用户投票状态 (true/false/null)

    # ── 时间 ──
    created: float | None = None  # 创建时间 (Unix timestamp)
    created_utc: float | None = None  # 创建时间 (UTC Unix timestamp)

    # ── 媒体 ──
    media: dict | None = None  # 嵌入媒体信息 (视频帖等)
    media_embed: dict | None = None  # 嵌入媒体展示配置
    secure_media: dict | None = None  # 安全媒体信息
    secure_media_embed: dict | None = None  # 安全嵌入媒体配置
    media_only: bool | None = None  # 是否仅媒体
    media_metadata: dict[str, MediaMetadataItem] | None = None  # gallery 图片元数据 (key=media_id)
    gallery_data: GalleryData | None = None  # gallery 画廊排序数据
    preview: Preview | None = None  # 预览数据 (普通图片帖)

    # ── Flair ──
    link_flair_text: str | None = None  # 帖子 flair 文字
    link_flair_text_color: str | None = None  # 帖子 flair 文字颜色: dark / light
    link_flair_type: str | None = None  # 帖子 flair 类型: text / richtext
    link_flair_css_class: str | None = None  # 帖子 flair CSS 类
    link_flair_background_color: str | None = None  # 帖子 flair 背景色
    link_flair_richtext: list[dict] | None = None  # 帖子 flair 富文本

    # ── 版务 ──
    approved_at_utc: float | None = None  # 审核通过时间
    approved_by: str | None = None  # 审核人
    banned_at_utc: float | None = None  # 封禁时间
    banned_by: str | None = None  # 封禁人
    removed_by: str | None = None  # 移除人
    removed_by_category: str | None = None  # 移除分类
    removal_reason: str | None = None  # 移除原因
    mod_reason_title: str | None = None  # 版务操作原因标题
    mod_reason_by: str | None = None  # 版务操作执行者
    mod_note: str | None = None  # 版主备注
    mod_reports: list[list] | None = None  # 版主举报
    user_reports: list[list] | None = None  # 用户举报
    report_reasons: list[str] | None = None  # 举报原因列表
    can_mod_post: bool | None = None  # 当前用户能否管理此帖
    distinguished: str | None = None  # 是否被标记为特殊 (moderator / admin)

    # ── 杂项 ──
    category: str | None = None  # 帖子分类
    content_categories: list[str] | None = None  # 内容分类列表
    discussion_type: str | None = None  # 讨论类型
    suggested_sort: str | None = None  # 建议的评论排序
    treatment_tags: list[str] | None = None  # 处理标签 (A/B 测试等)
    allow_live_comments: bool | None = None  # 是否允许实时评论
    can_gild: bool | None = None  # 当前用户能否 gild
    pwls: int | None = None  # 帖子白名单状态
    wls: int | None = None  # 白名单状态 (广告安全等级)

    model_config = {"extra": "allow", "populate_by_name": True}


class ListingChild(BaseModel):
    """Listing 中的单个子项 (帖子包装)"""

    kind: str | None = None  # 类型标识, e.g. "t3" (帖子), "t1" (评论)
    data: PostData | None = None  # 帖子数据


class ListingData(BaseModel):
    """Listing 的 data 部分"""

    after: str | None = None  # 下一页游标
    before: str | None = None  # 上一页游标
    dist: int | None = None  # 返回的子项数量
    modhash: str | None = None  # modhash (CSRF token)
    geo_filter: str | None = None  # 地理过滤器
    children: list[ListingChild] | None = None  # 帖子列表


class SubredditListing(BaseModel):
    """get_subreddit 返回的完整 Listing 响应"""

    kind: str | None = None  # 固定值 "Listing"
    data: ListingData | None = None  # 列表数据
