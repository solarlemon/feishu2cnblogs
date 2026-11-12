"""博客园 MetaWeblog（XML-RPC）客户端。

博客园接口要点
    · 端点 https://rpc.cnblogs.com/metaweblog/{博客名}
    · 密码是后台「设置 → 开放 API」里生成的访问令牌，不是登录密码
    · 发 Markdown 必须在分类里带 [Markdown]，否则页面显示原始 Markdown 源码
    · editPost 是整体替换：必须先 getPost 拿到原结构再改，否则标题/分类会丢
    · newMediaObject 用来把图片传到博客园图床，返回永久 URL
"""

from __future__ import annotations

import copy
import mimetypes
import socket
import ssl
import xmlrpc.client

from .config import Config
from .util import AppError, CnblogsError

TAG_HINT = "检查博客名、用户名和访问令牌；令牌要在博客园后台「设置 → 开放 API」里生成并启用。"


def _extract_post_id(value) -> str:
    if isinstance(value, bytes):
        value = value.decode("utf-8", errors="replace")
    text = str(value).strip().strip('"')
    return text


class CnblogsClient:
    def __init__(self, cfg: Config, *, timeout: float = 60):
        self.config = cfg
        self.settings = cfg.cnblogs
        if not self.settings.ready():
            raise AppError(self.settings.missing_hint())
        self.endpoint = self.settings.api_endpoint()
        self.username = self.settings.username
        self.token = self.settings.token
        self.blog_id = self.settings.blog or "cnblogs"
        self.timeout = timeout

    # ------------------------------------------------------------------
    def _server(self) -> xmlrpc.client.ServerProxy:
        transport = _TimeoutSafeTransport(self.timeout, ssl.create_default_context())
        return xmlrpc.client.ServerProxy(
            self.endpoint, transport=transport, allow_none=False, use_builtin_types=True
        )

    def _call(self, method: str, params: list):
        server = self._server()
        target = server
        for part in method.split("."):
            target = getattr(target, part)
        try:
            return target(*params)
        except xmlrpc.client.Fault as fault:
            raise CnblogsError(
                "博客园返回错误：%s\n%s" % (fault.faultString, TAG_HINT)
            )
        except xmlrpc.client.ProtocolError as exc:
            raise CnblogsError(
                "博客园协议错误：HTTP %s %s（%s）" % (exc.errcode, exc.errmsg, self.endpoint)
            )
        except (socket.timeout, TimeoutError):
            raise CnblogsError("连接博客园超时，请稍后重试：%s" % self.endpoint)
        except OSError as exc:
            raise CnblogsError("连接博客园失败：%s（%s）" % (exc, self.endpoint))

    # ------------------------------------------------------------------
    def check(self) -> dict:
        """验证凭据，顺便拿到博客信息。"""
        blogs = self._call(
            "blogger.getUsersBlogs", [self.blog_id, self.username, self.token]
        )
        return {"blogs": blogs or [], "endpoint": self.endpoint}

    def get_categories(self) -> list:
        try:
            items = self._call(
                "metaWeblog.getCategories", [self.blog_id, self.username, self.token]
            )
        except CnblogsError:
            return []
        names = []
        for item in items or []:
            if isinstance(item, dict):
                name = item.get("title") or item.get("categoryName") or ""
                if name:
                    names.append(str(name))
        return names

    def upload_media(self, data: bytes, name: str, mime: str | None = None) -> str:
        mime = mime or mimetypes.guess_type(name)[0] or "application/octet-stream"
        media = {
            "name": name,
            "type": mime,
            "bits": xmlrpc.client.Binary(data),
        }
        result = self._call(
            "metaWeblog.newMediaObject",
            [self.blog_id, self.username, self.token, media],
        )
        url = ""
        if isinstance(result, dict):
            url = result.get("url") or result.get("link") or ""
        if not url:
            raise CnblogsError("图片上传成功但没拿到 URL：%s" % name)
        return str(url)

    def get_post(self, post_id: str) -> dict:
        post = self._call("metaWeblog.getPost", [post_id, self.username, self.token])
        if not isinstance(post, dict):
            raise CnblogsError("读取文章失败：%s" % post_id)
        return post

    def new_post(self, post: dict, *, publish: bool = True) -> str:
        result = self._call(
            "metaWeblog.newPost",
            [self.blog_id, self.username, self.token, post, bool(publish)],
        )
        return _extract_post_id(result)

    def edit_post(self, post_id: str, post: dict, *, publish: bool = True) -> bool:
        current = self.get_post(post_id)
        merged = copy.deepcopy(current)
        merged.update(post)
        merged.pop("postid", None)
        result = self._call(
            "metaWeblog.editPost",
            [post_id, self.username, self.token, merged, bool(publish)],
        )
        return bool(result)

    def post_url(self, post_id: str, post: dict | None = None) -> str:
        if post:
            for key in ("link", "permalink", "url"):
                if post.get(key):
                    return str(post[key])
        return self.settings.post_url(post_id)


class _TimeoutSafeTransport(xmlrpc.client.SafeTransport):
    def __init__(self, timeout: float, context: ssl.SSLContext):
        super().__init__(context=context)
        self._timeout = timeout

    def make_connection(self, host):
        conn = super().make_connection(host)
        try:
            conn.timeout = self._timeout
        except Exception:
            pass
        return conn
