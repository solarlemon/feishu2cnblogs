"""配置：读取 / 保存 / 环境变量覆盖 / 路径解析。

凭据优先级：命令行参数 > 环境变量 > 配置文件。

环境变量
    FEISHU_APP_ID / FEISHU_APP_SECRET / FEISHU_USER_TOKEN / FEISHU_BASE_URL
    CNBLOGS_USERNAME / CNBLOGS_TOKEN / CNBLOGS_BLOG / CNBLOGS_ENDPOINT

配置文件默认放在 ~/.feishu2cnblogs/config.json（可用 --config 指定）。
"""

from __future__ import annotations

import os
from dataclasses import asdict, dataclass, field

from .util import UsageError, read_json, write_json

DEFAULT_BASE_URL = "https://open.feishu.cn"
DEFAULT_MARKDOWN_CATEGORY = "[Markdown]"
DEFAULT_ENDPOINT_TEMPLATE = "https://rpc.cnblogs.com/metaweblog/{blog}"


@dataclass
class FeishuConfig:
    app_id: str = ""
    app_secret: str = ""
    # 可选：不填就用 tenant_access_token（自建应用）；填了就优先用它访问文档
    user_token: str = ""
    base_url: str = DEFAULT_BASE_URL

    def ready(self) -> bool:
        return bool((self.app_id and self.app_secret) or self.user_token)

    def missing_hint(self) -> str:
        return (
            "还没有配置飞书应用凭证。任选一种方式：\n"
            "  1) 运行  python -m feishu2cnblogs init\n"
            "  2) 设置环境变量 FEISHU_APP_ID 和 FEISHU_APP_SECRET"
        )


@dataclass
class CnblogsConfig:
    username: str = ""
    token: str = ""
    blog: str = ""
    endpoint: str = ""          # 留空则按 blog 自动拼
    blog_url: str = ""          # 留空则按 blog 自动拼
    markdown_category: str = DEFAULT_MARKDOWN_CATEGORY
    categories: list = field(default_factory=list)
    tags: list = field(default_factory=list)
    add_ai_declaration: bool = False
    add_source_link: bool = False
    max_image_mb: int = 10

    def ready(self) -> bool:
        return bool(self.username and self.token and self.blog)

    def missing_hint(self) -> str:
        return (
            "还没有配置博客园凭据。任选一种方式：\n"
            "  1) 运行  python -m feishu2cnblogs init\n"
            "  2) 设置环境变量 CNBLOGS_USERNAME、CNBLOGS_BLOG、CNBLOGS_TOKEN\n"
            "令牌在 博客园后台 → 设置 → 开放 API 里生成（不是登录密码）。"
        )

    def api_endpoint(self) -> str:
        if self.endpoint:
            return self.endpoint.strip()
        return DEFAULT_ENDPOINT_TEMPLATE.format(blog=self.blog.strip())

    def post_url(self, post_id: str) -> str:
        base = (self.blog_url or "https://www.cnblogs.com/%s" % self.blog.strip()).rstrip("/")
        return "%s/p/%s" % (base, post_id)


@dataclass
class Config:
    feishu: FeishuConfig = field(default_factory=FeishuConfig)
    cnblogs: CnblogsConfig = field(default_factory=CnblogsConfig)
    # 本地状态文件（记录已发布过的文章，用于幂等更新），相对配置文件所在目录
    state_path: str = ""
    path: str = ""

    def dir(self) -> str:
        return os.path.dirname(os.path.abspath(self.path)) if self.path else os.getcwd()

    def resolve_state_path(self) -> str:
        if self.state_path:
            if os.path.isabs(self.state_path):
                return self.state_path
            return os.path.join(self.dir(), self.state_path)
        return os.path.join(self.dir(), "state.json")

    def to_json(self) -> dict:
        data = asdict(self)
        data.pop("path", None)
        return data

    # ------------------------------------------------------------------
    def save(self) -> None:
        write_json(self.path, self.to_json())


def default_config_path() -> str:
    home = os.path.expanduser("~")
    return os.path.join(home, ".feishu2cnblogs", "config.json")


def _env(name: str) -> str:
    return (os.environ.get(name) or "").strip()


def _as_bool(value, default: bool) -> bool:
    if isinstance(value, bool):
        return value
    if isinstance(value, str):
        return value.strip().lower() in ("1", "true", "yes", "on")
    return default


def _as_list(value) -> list:
    if not value:
        return []
    if isinstance(value, str):
        parts = value.replace("，", ",").split(",")
        return [p.strip() for p in parts if p.strip()]
    if isinstance(value, (list, tuple)):
        return [str(p).strip() for p in value if str(p).strip()]
    return []


def load_config(path: str | None = None, *, use_env: bool = True) -> Config:
    path = os.path.abspath(path or default_config_path())
    raw = read_json(path, default={}) or {}
    if not isinstance(raw, dict):
        raise UsageError("配置文件格式不正确：%s" % path)

    feishu_raw = raw.get("feishu") or {}
    cnblogs_raw = raw.get("cnblogs") or {}
    if not isinstance(feishu_raw, dict) or not isinstance(cnblogs_raw, dict):
        raise UsageError("配置文件里的 feishu / cnblogs 必须是对象：%s" % path)

    cfg = Config(
        feishu=FeishuConfig(
            app_id=str(feishu_raw.get("app_id") or ""),
            app_secret=str(feishu_raw.get("app_secret") or ""),
            user_token=str(feishu_raw.get("user_token") or ""),
            base_url=str(feishu_raw.get("base_url") or DEFAULT_BASE_URL).rstrip("/"),
        ),
        cnblogs=CnblogsConfig(
            username=str(cnblogs_raw.get("username") or ""),
            token=str(cnblogs_raw.get("token") or ""),
            blog=str(cnblogs_raw.get("blog") or ""),
            endpoint=str(cnblogs_raw.get("endpoint") or ""),
            blog_url=str(cnblogs_raw.get("blog_url") or ""),
            markdown_category=str(cnblogs_raw.get("markdown_category") or DEFAULT_MARKDOWN_CATEGORY),
            categories=_as_list(cnblogs_raw.get("categories")),
            tags=_as_list(cnblogs_raw.get("tags")),
            add_ai_declaration=_as_bool(cnblogs_raw.get("add_ai_declaration"), False),
            add_source_link=_as_bool(cnblogs_raw.get("add_source_link"), False),
            max_image_mb=int(cnblogs_raw.get("max_image_mb") or 10),
        ),
        state_path=str(raw.get("state_path") or ""),
        path=path,
    )

    if use_env:
        cfg.feishu.app_id = _env("FEISHU_APP_ID") or cfg.feishu.app_id
        cfg.feishu.app_secret = _env("FEISHU_APP_SECRET") or cfg.feishu.app_secret
        cfg.feishu.user_token = _env("FEISHU_USER_TOKEN") or cfg.feishu.user_token
        cfg.feishu.base_url = (_env("FEISHU_BASE_URL") or cfg.feishu.base_url).rstrip("/")
        cfg.cnblogs.username = _env("CNBLOGS_USERNAME") or cfg.cnblogs.username
        cfg.cnblogs.blog = _env("CNBLOGS_BLOG") or cfg.cnblogs.blog
        cfg.cnblogs.token = _env("CNBLOGS_TOKEN") or cfg.cnblogs.token
        cfg.cnblogs.endpoint = _env("CNBLOGS_ENDPOINT") or cfg.cnblogs.endpoint
        if _env("CNBLOGS_CATEGORIES"):
            cfg.cnblogs.categories = _as_list(_env("CNBLOGS_CATEGORIES"))
        if _env("CNBLOGS_TAGS"):
            cfg.cnblogs.tags = _as_list(_env("CNBLOGS_TAGS"))
    return cfg


def save_config(cfg: Config) -> None:
    cfg.save()


def secrets_of(cfg: Config) -> list:
    """用于日志脱敏的敏感值列表。"""
    return [
        cfg.feishu.app_secret,
        cfg.feishu.user_token,
        cfg.cnblogs.token,
    ]
