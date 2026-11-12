"""飞书开放平台客户端：只做「读文档」这一件事。

用到的接口
    1. POST /open-apis/auth/v3/tenant_access_token/internal   拿应用凭证
    2. GET  /open-apis/wiki/v2/spaces/get_node               把 wiki 节点换成真实文档 token
    3. GET  /open-apis/docx/v1/documents/{id}                文档元信息（标题等）
    4. GET  /open-apis/docx/v1/documents/{id}/blocks         全部块（分页）
    5. GET  /open-apis/docx/v1/documents/{id}/raw_content    纯文本（备用）
    6. GET  /open-apis/drive/v1/medias/{token}/download      下载图片

凭证优先级：配置里的 user_token > 自建应用的 tenant_access_token。
自建应用要能读到文档，需要在飞书文档右上角「…」→「添加文档应用」里把这个应用加进去。
"""

from __future__ import annotations

import json
import mimetypes
import os
import re
import time
import urllib.parse

from .config import Config
from .util import AppError, FeishuError, NetworkError, http_request, info

TOKEN_HINT = (
    "常见原因：\n"
    "  · 文档没有授权给这个应用 —— 打开文档 → 右上角「…」→「添加文档应用」，把应用加为协作者；\n"
    "  · 应用没开通云文档权限 —— 开发者后台 → 权限管理 → 添加 docx:document:readonly、wiki:wiki:readonly 等；\n"
    "  · 应用还在企业内测/未发布，先用同一应用身份访问一次；\n"
    "  · 用 user_token 时确认它没过期。"
)

_WIKI_RE = re.compile(r"/wiki/([A-Za-z0-9_-]+)")
_DOCX_RE = re.compile(r"/docx/([A-Za-z0-9_-]+)")
_LEGACY_DOC_RE = re.compile(r"/docs/([A-Za-z0-9_-]+)")
_SHEET_RE = re.compile(r"/(sheets|base|mindnotes|slides)/([A-Za-z0-9_-]+)")
_TOKEN_ONLY_RE = re.compile(r"^[A-Za-z0-9_-]{10,}$")

OBJ_TYPE_NAMES = {1: "旧版文档 doc", 3: "电子表格", 8: "多维表格", 11: "思维笔记",
                  12: "文件", 15: "幻灯片", 16: "wiki 节点", 22: "新版文档 docx"}


def parse_document_ref(ref: str) -> dict:
    """把飞书文档链接 / token / wiki 链接解析成 {token, kind}。

    kind: docx | wiki | doc | sheet | base | file
    """
    ref = (ref or "").strip()
    if not ref:
        raise AppError("文档链接或 token 不能为空")

    match = _WIKI_RE.search(ref)
    if match:
        return {"token": match.group(1), "kind": "wiki"}
    match = _DOCX_RE.search(ref)
    if match:
        return {"token": match.group(1), "kind": "docx"}
    match = _LEGACY_DOC_RE.search(ref)
    if match:
        return {"token": match.group(1), "kind": "doc"}
    match = _SHEET_RE.search(ref)
    if match:
        return {"token": match.group(2), "kind": match.group(1)}
    if _TOKEN_ONLY_RE.match(ref):
        # 裸 token 当 docx 处理，失败时再退回 wiki 尝试
        return {"token": ref, "kind": "docx"}
    raise AppError(
        "看不懂这个飞书文档引用：%s\n"
        "支持的形式：\n"
        "  https://xxx.feishu.cn/docx/XXXX\n"
        "  https://xxx.feishu.cn/wiki/XXXX\n"
        "  直接粘贴文档 token（docx/ 或 wiki/ 后面那一串）" % ref
    )


class FeishuClient:
    def __init__(self, cfg: Config, *, timeout: float = 60):
        self.config = cfg
        self.feishu = cfg.feishu
        self.base_url = (self.feishu.base_url or "https://open.feishu.cn").rstrip("/")
        self.timeout = timeout
        self._token = None
        self._token_expire_at = 0.0

    # ------------------------------------------------------------------
    # 底层请求
    # ------------------------------------------------------------------
    def _auth_header(self) -> dict:
        if self.feishu.user_token:
            return {"Authorization": "Bearer %s" % self.feishu.user_token}
        return {"Authorization": "Bearer %s" % self.tenant_token()}

    def tenant_token(self) -> str:
        if self._token and time.time() < self._token_expire_at:
            return self._token
        if not (self.feishu.app_id and self.feishu.app_secret):
            raise AppError(
                "没有飞书应用凭证，也没有 user_token。\n" + self.feishu.missing_hint()
            )
        url = self.base_url + "/open-apis/auth/v3/tenant_access_token/internal"
        payload = json.dumps(
            {"app_id": self.feishu.app_id, "app_secret": self.feishu.app_secret}
        ).encode("utf-8")
        resp = http_request(
            "POST", url,
            headers={"Content-Type": "application/json; charset=utf-8"},
            body=payload, timeout=self.timeout,
        )
        data = resp.json()
        if data.get("code") != 0:
            raise FeishuError(
                data.get("code"), data.get("msg") or "获取 tenant_access_token 失败",
                path="auth/v3/tenant_access_token/internal",
                hint="检查 App ID / App Secret 是否填对，以及应用是否已启用。",
            )
        self._token = data["tenant_access_token"]
        # 提前 5 分钟过期，避免边界
        self._token_expire_at = time.time() + max(int(data.get("expire", 7200)) - 300, 60)
        return self._token

    def request(self, method: str, path: str, *, params=None, body=None) -> dict:
        url = self.base_url + path
        if params:
            url += "?" + urllib.parse.urlencode({k: v for k, v in params.items() if v is not None})
        payload = None
        headers = dict(self._auth_header())
        if body is not None:
            payload = json.dumps(body).encode("utf-8")
            headers["Content-Type"] = "application/json; charset=utf-8"
        resp = http_request(method, url, headers=headers, body=payload, timeout=self.timeout)
        try:
            data = resp.json()
        except NetworkError:
            raise FeishuError(-1, "返回内容不是 JSON（HTTP %s）" % resp.status, path=path)
        if data.get("code") != 0:
            raise FeishuError(data.get("code"), data.get("msg") or "请求失败", path=path, hint=TOKEN_HINT)
        return data.get("data") or {}

    # ------------------------------------------------------------------
    # 文档
    # ------------------------------------------------------------------
    def resolve_wiki_node(self, token: str) -> dict:
        """wiki 节点 → 真实文档 token。"""
        data = self.request("GET", "/open-apis/wiki/v2/spaces/get_node", params={"token": token})
        node = data.get("node") or {}
        obj_type = node.get("obj_type")
        obj_token = node.get("obj_token")
        if not obj_token:
            raise FeishuError(-1, "wiki 节点没有返回 obj_token", path="wiki/v2/spaces/get_node")
        return {
            "obj_token": obj_token,
            "obj_type": obj_type,
            "obj_type_name": OBJ_TYPE_NAMES.get(obj_type, str(obj_type)),
            "title": node.get("title") or "",
            "space_id": node.get("space_id"),
            "node_token": token,
        }

    def get_document_meta(self, doc_id: str) -> dict:
        try:
            data = self.request("GET", "/open-apis/docx/v1/documents/%s" % doc_id)
        except FeishuError:
            return {}
        return data.get("document") or {}

    def get_all_blocks(self, doc_id: str, *, page_size: int = 500, max_pages: int = 100) -> list:
        blocks = []
        page_token = None
        for _ in range(max_pages):
            params = {"page_size": page_size, "document_revision_id": -1}
            if page_token:
                params["page_token"] = page_token
            data = self.request(
                "GET", "/open-apis/docx/v1/documents/%s/blocks" % doc_id, params=params
            )
            items = data.get("items") or []
            blocks.extend(items)
            page_token = data.get("page_token")
            if not data.get("has_more") or not page_token:
                return blocks
        raise AppError("文档块超过 %d 页，已中止（文档过大？）" % max_pages)

    def get_raw_content(self, doc_id: str) -> str:
        data = self.request(
            "GET", "/open-apis/docx/v1/documents/%s/raw_content" % doc_id,
            params={"lang": 0},
        )
        return data.get("content") or ""

    def download_media(self, file_token: str) -> tuple:
        """下载文档内媒体，返回 (bytes, mime)。飞书会 302 到签名地址。"""
        path = "/open-apis/drive/v1/medias/%s/download" % urllib.parse.quote(file_token)
        url = self.base_url + path
        resp = http_request("GET", url, headers=self._auth_header(), timeout=self.timeout)
        mime = ""
        for key, value in (resp.headers or {}).items():
            if key.lower() == "content-type":
                mime = value
                break
        if not mime or mime == "application/octet-stream":
            mime = mimetypes.guess_type("x.bin")[0] or "application/octet-stream"
        return resp.body, mime

    # ------------------------------------------------------------------
    def load_document(self, ref: str) -> dict:
        """把链接/token 变成 {doc_id, title, blocks, source} 。

        供转换器直接使用，也供 --dump-blocks 调试。
        """
        parsed = parse_document_ref(ref)
        kind = parsed["kind"]
        token = parsed["token"]
        node_info = None

        if kind == "wiki":
            info("解析 wiki 节点 %s …" % token)
            node_info = self.resolve_wiki_node(token)
            if node_info["obj_type"] != 22:
                raise AppError(
                    "这个 wiki 节点是「%s」，不是新版文档 docx，暂不支持。\n"
                    "目前支持：新版文档 docx（含 wiki 里的 docx）。" % node_info["obj_type_name"]
                )
            doc_id = node_info["obj_token"]
        elif kind == "docx":
            doc_id = token
        elif kind == "doc":
            raise AppError(
                "这是旧版文档（/docs/ 开头），飞书没有开放它的块结构。\n"
                "请在飞书里「…」→「转为新版文档」后重试。"
            )
        elif kind in ("sheet", "sheets", "base"):
            raise AppError("当前版本只支持新版文档 docx，暂不支持%s。" % (
                "电子表格" if kind in ("sheet", "sheets") else "多维表格"))
        else:
            raise AppError("不支持的文档类型：%s" % kind)

        blocks = self.get_all_blocks(doc_id)
        if not blocks:
            raise AppError("文档里没有读到任何内容（doc_id=%s）。" % doc_id)

        meta = self.get_document_meta(doc_id)
        title = ""
        if node_info and node_info.get("title"):
            title = node_info["title"]
        if not title:
            title = meta.get("title") or ""
        if not title:
            for block in blocks:
                if block.get("block_type") == 1:
                    title = _block_plain_text(block) or ""
                    break
        if not title:
            title = meta.get("display_name") or "未命名文档"

        return {
            "doc_id": doc_id,
            "title": title.strip(),
            "blocks": blocks,
            "source": ref,
            "revision_id": meta.get("revision_id"),
            "wiki_node": node_info,
        }


def _block_plain_text(block: dict) -> str:
    """从一个块里取出纯文本（给标题兜底用）。"""
    for key in ("page", "text", "heading1", "heading2", "heading3", "heading4",
                "heading5", "heading6", "bullet", "ordered", "code", "quote",
                "todo", "callout"):
        node = block.get(key)
        if not isinstance(node, dict):
            continue
        parts = []
        for element in node.get("elements") or []:
            run = (element or {}).get("text_run") or {}
            parts.append(run.get("content") or "")
        text = "".join(parts).strip()
        if text:
            return text
    return ""


def safe_filename(name: str, fallback: str = "document") -> str:
    name = (name or "").strip()
    name = re.sub(r'[\\/:*?"<>|\r\n\t]+', "_", name)
    name = name.strip(" .")
    return name[:80] or fallback


def guess_extension(mime: str) -> str:
    ext = mimetypes.guess_extension((mime or "").split(";")[0].strip()) or ""
    return ext or ".png"


def ensure_parent(path: str) -> None:
    parent = os.path.dirname(os.path.abspath(path))
    if parent:
        os.makedirs(parent, exist_ok=True)
