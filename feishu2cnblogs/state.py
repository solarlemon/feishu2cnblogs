"""本地状态：记住「哪个飞书文档已经发成哪篇博客园文章」。

有它才能做到重复发布时自动更新同一篇，而不是每跑一次就多一篇文章。
状态文件默认与配置文件同目录（state.json），记录内容不含令牌。
"""

from __future__ import annotations

import datetime
import hashlib
import os

from .util import read_json, write_json


def _now() -> str:
    return datetime.datetime.now().astimezone().isoformat(timespec="seconds")


def content_hash(text: str) -> str:
    return hashlib.sha256((text or "").encode("utf-8")).hexdigest()[:16]


class StateStore:
    def __init__(self, path: str):
        self.path = path
        raw = read_json(path, default=None) or {}
        if not isinstance(raw, dict):
            raw = {}
        self.data = raw
        self.data.setdefault("version", 1)
        self.data.setdefault("posts", {})

    @property
    def posts(self) -> dict:
        return self.data["posts"]

    def get(self, doc_id: str) -> dict | None:
        return self.posts.get(doc_id)

    def record(self, doc_id: str, **fields) -> dict:
        entry = self.posts.get(doc_id) or {"doc_id": doc_id, "created_at": _now()}
        entry.update(fields)
        entry["updated_at"] = _now()
        self.posts[doc_id] = entry
        return entry

    def remove(self, doc_id: str) -> bool:
        return self.posts.pop(doc_id, None) is not None

    def save(self) -> None:
        write_json(self.path, self.data)

    def all(self) -> list:
        items = list(self.posts.values())
        items.sort(key=lambda item: item.get("updated_at") or "", reverse=True)
        return items


class ImageUploader:
    """把飞书图片下载下来，再传到博客园图床。

    同一次运行里同一张图只传一次（按 feishu token 缓存）。
    on_image(index, total, message) 用于把进度报给调用方（网页版会实时显示）。
    """

    def __init__(self, feishu, blog, *, max_mb: int = 10):
        self.feishu = feishu
        self.blog = blog
        self.max_bytes = max_mb * 1024 * 1024
        self.cache = {}
        self.warnings = []

    def upload_tokens(self, tokens, registry, *, on_image=None) -> dict:
        mapping = {}
        total = len(tokens)
        for index, token in enumerate(tokens, 1):
            image = registry.items.get(token)
            name = image.name if image else "image.png"
            try:
                data, mime = self.feishu.download_media(token)
                if len(data) > self.max_bytes:
                    raise ValueError(
                        "图片 %.1f MB，超过上限 %d MB"
                        % (len(data) / 1024 / 1024, self.max_bytes // (1024 * 1024))
                    )
                if not name.lower().endswith((".png", ".jpg", ".jpeg", ".gif", ".webp", ".bmp", ".svg")):
                    ext = ".png"
                    if "jpeg" in mime:
                        ext = ".jpg"
                    elif "gif" in mime:
                        ext = ".gif"
                    elif "webp" in mime:
                        ext = ".webp"
                    name = os.path.splitext(name)[0] + ext
                url = self.blog.upload_media(data, name, mime)
                mapping[token] = url
                message = "图片 %d/%d 已上传：%s" % (index, total, url)
                if on_image:
                    on_image(index, total, message)
                else:
                    print("  · " + message)
            except Exception as exc:  # 单张图失败不阻断整篇发布
                self.warnings.append("图片上传失败（%s）：%s" % (name, exc))
                message = "图片 %d/%d 上传失败（%s）：%s" % (index, total, name, exc)
                if on_image:
                    on_image(index, total, message)
                else:
                    print("  ! " + message)
        return mapping
