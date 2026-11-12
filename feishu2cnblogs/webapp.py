"""本地网页版：浏览器里粘贴飞书链接 → 预览 → 一键发布。

只用标准库的 http.server，绑定 127.0.0.1，不需要装任何东西。

安全性
    · 只监听本机回环地址
    · 每次启动生成随机 token，写操作必须带 X-Token 头（页面从 /api/session 拿）
    · 校验 Origin / Host，挡住其他网站对 localhost 的跨站请求
    · /api/config 只返回打码后的凭据
"""

from __future__ import annotations

import json
import mimetypes
import os
import secrets
import sys
import threading
import time
import traceback
import urllib.parse
import webbrowser
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

from . import __version__
from .blog import CnblogsClient
from .config import load_config, save_config
from .converter import collect_image_tokens, replace_image_placeholders
from .feishu import FeishuClient, safe_filename
from .pipeline import PublishOptions, load_document, parse_meta_block, publish
from .state import StateStore
from .util import AppError, UsageError, redact

WEB_DIR = os.path.join(os.path.dirname(os.path.abspath(__file__)), "web")
MAX_BODY = 1024 * 1024

# Windows 的注册表常把 .js 映射成 text/plain，配合 nosniff 会直接被浏览器拒绝执行，
# 所以静态资源用固定的 MIME 表，不依赖 mimetypes。
STATIC_TYPES = {
    ".html": "text/html; charset=utf-8",
    ".js": "text/javascript; charset=utf-8",
    ".css": "text/css; charset=utf-8",
    ".svg": "image/svg+xml",
    ".png": "image/png",
    ".jpg": "image/jpeg",
    ".jpeg": "image/jpeg",
    ".webp": "image/webp",
    ".ico": "image/x-icon",
    ".json": "application/json; charset=utf-8",
    ".woff2": "font/woff2",
}


def _mask(value: str) -> str:
    value = value or ""
    if not value:
        return ""
    if len(value) <= 6:
        return "••••"
    return value[:4] + "••••" + value[-2:]


def _pretty_path(path: str) -> str:
    """把用户主目录缩成 ~，界面上不暴露完整本机路径。"""
    home = os.path.expanduser("~")
    if path and home and path.startswith(home):
        return "~" + path[len(home):].replace("\\", "/")
    return (path or "").replace("\\", "/")


class App:
    """把配置、任务、图片缓存集中起来，Handler 只做 HTTP 层。"""

    def __init__(self, config_path: str | None = None):
        self.config_path = config_path
        self.cfg = load_config(config_path)
        self.token = secrets.token_urlsafe(18)
        self.jobs = {}
        self.jobs_lock = threading.Lock()
        self.media_cache = {}
        self.media_lock = threading.Lock()
        self.started_at = time.time()

    # ---- 配置 ----
    def reload(self) -> None:
        self.cfg = load_config(self.config_path)

    def public_config(self) -> dict:
        self.reload()
        cfg = self.cfg
        return {
            "ok": True,
            "version": __version__,
            "config_path": _pretty_path(cfg.path),
            "state_path": _pretty_path(cfg.resolve_state_path()),
            "feishu": {
                "app_id": cfg.feishu.app_id,
                "app_secret": _mask(cfg.feishu.app_secret),
                "has_secret": bool(cfg.feishu.app_secret),
                "user_token": _mask(cfg.feishu.user_token),
                "has_user_token": bool(cfg.feishu.user_token),
                "base_url": cfg.feishu.base_url,
                "ready": cfg.feishu.ready(),
            },
            "cnblogs": {
                "username": cfg.cnblogs.username,
                "blog": cfg.cnblogs.blog,
                "token": _mask(cfg.cnblogs.token),
                "has_token": bool(cfg.cnblogs.token),
                "categories": cfg.cnblogs.categories,
                "tags": cfg.cnblogs.tags,
                "markdown_category": cfg.cnblogs.markdown_category,
                "ready": cfg.cnblogs.ready(),
            },
        }

    def save_config(self, payload: dict) -> dict:
        cfg = load_config(self.config_path, use_env=False)
        feishu = payload.get("feishu") or {}
        cnblogs = payload.get("cnblogs") or {}

        for key in ("app_id", "app_secret", "user_token", "base_url"):
            value = (feishu.get(key) or "").strip()
            if value:
                setattr(cfg.feishu, key, value)
        for key in ("username", "blog", "token"):
            value = (cnblogs.get(key) or "").strip()
            if value:
                setattr(cfg.cnblogs, key, value)
        if "categories" in cnblogs:
            cfg.cnblogs.categories = [
                item.strip() for item in str(cnblogs["categories"]).replace("，", ",").split(",")
                if item.strip()
            ]
        if "tags" in cnblogs:
            cfg.cnblogs.tags = [
                item.strip() for item in str(cnblogs["tags"]).replace("，", ",").split(",")
                if item.strip()
            ]
        save_config(cfg)
        self.reload()
        return self.public_config()

    # ---- 预览 ----
    def preview(self, ref: str) -> dict:
        self.reload()
        if not self.cfg.feishu.ready():
            raise AppError(self.cfg.feishu.missing_hint())
        feishu, document, result = load_document(self.cfg, ref)
        meta, body = parse_meta_block(result.markdown)
        markdown = body if meta else result.markdown

        tokens = collect_image_tokens(markdown)
        preview_md = replace_image_placeholders(
            markdown, {token: "/api/image/%s" % token for token in tokens}
        )
        store = StateStore(self.cfg.resolve_state_path())
        existing = store.get(document["doc_id"])

        return {
            "ok": True,
            "doc_id": document["doc_id"],
            "doc_title": document["title"],
            "title": meta.get("title") or result.title,
            "markdown": markdown,
            "preview": preview_md,
            "blocks": len(document["blocks"]),
            "chars": len(markdown),
            "images": len(tokens),
            "warnings": result.warnings,
            "meta": meta,
            "existing": existing,
            "defaults": {
                "categories": self.cfg.cnblogs.categories,
                "tags": self.cfg.cnblogs.tags,
            },
        }

    # ---- 图片代理（预览时直接显示飞书图） ----
    def media(self, token: str) -> tuple:
        with self.media_lock:
            cached = self.media_cache.get(token)
            if cached:
                return cached
        feishu = FeishuClient(self.cfg)
        data, mime = feishu.download_media(token)
        if len(data) > 20 * 1024 * 1024:
            raise AppError("图片过大，无法预览")
        with self.media_lock:
            if len(self.media_cache) > 80:
                self.media_cache.clear()
            self.media_cache[token] = (data, mime)
        return data, mime

    # ---- 连通性 ----
    def check(self, doc: str | None) -> dict:
        self.reload()
        result = {"ok": True, "feishu": {}, "cnblogs": {}}
        try:
            if not self.cfg.feishu.ready():
                raise AppError(self.cfg.feishu.missing_hint())
            client = FeishuClient(self.cfg)
            if not self.cfg.feishu.user_token:
                client.tenant_token()
            info = {"ok": True, "auth": "user_token" if self.cfg.feishu.user_token else "tenant_access_token"}
            if doc:
                document = client.load_document(doc)
                info["document"] = {"title": document["title"], "blocks": len(document["blocks"])}
            result["feishu"] = info
        except Exception as exc:
            result["ok"] = False
            result["feishu"] = {"ok": False, "error": str(exc)}

        try:
            if not self.cfg.cnblogs.ready():
                raise AppError(self.cfg.cnblogs.missing_hint())
            client = CnblogsClient(self.cfg)
            data = client.check()
            blogs = [b.get("blogName") or b.get("url") for b in data["blogs"] if isinstance(b, dict)]
            result["cnblogs"] = {"ok": True, "blogs": blogs, "endpoint": data["endpoint"]}
        except Exception as exc:
            result["ok"] = False
            result["cnblogs"] = {"ok": False, "error": str(exc)}
        return result

    # ---- 发布任务 ----
    def start_publish(self, payload: dict) -> str:
        self.reload()
        if not self.cfg.cnblogs.ready():
            raise AppError(self.cfg.cnblogs.missing_hint())
        ref = (payload.get("doc") or "").strip()
        if not ref:
            raise AppError("请先填写飞书文档链接")

        job_id = secrets.token_hex(8)
        job = {
            "id": job_id,
            "status": "running",
            "progress": 0,
            "message": "准备中…",
            "logs": [],
            "result": None,
            "error": None,
            "started_at": time.time(),
        }
        with self.jobs_lock:
            self.jobs[job_id] = job
            # 只保留最近 40 个任务
            if len(self.jobs) > 40:
                for key in sorted(self.jobs, key=lambda k: self.jobs[k]["started_at"])[:-40]:
                    self.jobs.pop(key, None)

        options = PublishOptions(
            categories=self._as_list(payload.get("categories")),
            tags=self._as_list(payload.get("tags")),
            title=(payload.get("title") or "").strip() or None,
            draft=not bool(payload.get("publish")),
            publish=bool(payload.get("publish")),
            force_new=bool(payload.get("forceNew")),
            upload_images=payload.get("uploadImages", True) is not False,
            ai_declaration=bool(payload.get("aiDeclaration")),
            source_link=bool(payload.get("sourceLink")),
            excerpt=(payload.get("summary") or "").strip() or None,
        )

        def worker():
            def progress(percent, message):
                job["progress"] = max(0, min(100, int(percent)))
                job["message"] = message
                job["logs"].append({"p": job["progress"], "m": message, "t": round(time.time() - job["started_at"], 1)})
                job["logs"] = job["logs"][-80:]

            try:
                result = publish(self.cfg, ref, options, progress=progress)
                job["result"] = {
                    "action": result.action,
                    "post_id": result.post_id,
                    "title": result.title,
                    "url": result.url,
                    "draft": result.draft,
                    "warnings": result.warnings,
                    "stats": result.stats,
                }
                job["status"] = "done"
                job["progress"] = 100
                job["message"] = "发布完成"
            except Exception as exc:
                job["status"] = "error"
                job["error"] = str(exc)
                job["message"] = "发布失败"

        thread = threading.Thread(target=worker, daemon=True)
        thread.start()
        return job_id

    def job(self, job_id: str) -> dict:
        with self.jobs_lock:
            job = self.jobs.get(job_id)
        if not job:
            raise AppError("任务不存在或已过期")
        return job

    # ---- 历史 ----
    def history(self) -> dict:
        self.reload()
        store = StateStore(self.cfg.resolve_state_path())
        return {"ok": True, "items": store.all(), "state_path": store.path}

    def forgot(self, doc_id: str) -> dict:
        store = StateStore(self.cfg.resolve_state_path())
        removed = store.remove(doc_id)
        if removed:
            store.save()
        return {"ok": True, "removed": removed}

    @staticmethod
    def _as_list(value) -> list:
        if not value:
            return []
        if isinstance(value, (list, tuple)):
            return [str(v).strip() for v in value if str(v).strip()]
        return [v.strip() for v in str(value).replace("，", ",").split(",") if v.strip()]


class Handler(BaseHTTPRequestHandler):
    server_version = "feishu2cnblogs/" + __version__
    app: App = None  # type: ignore

    # ---- 基础 ----
    def log_message(self, fmt, *args):
        if os.environ.get("F2C_DEBUG"):
            sys.stderr.write("[web] %s\n" % (fmt % args))

    def _send(self, status: int, body: bytes, content_type: str, extra=None):
        self.send_response(status)
        self.send_header("Content-Type", content_type)
        self.send_header("Content-Length", str(len(body)))
        self.send_header("Cache-Control", "no-store")
        self.send_header("X-Content-Type-Options", "nosniff")
        for key, value in (extra or {}).items():
            self.send_header(key, value)
        self.end_headers()
        try:
            self.wfile.write(body)
        except (BrokenPipeError, ConnectionResetError):
            pass

    def _json(self, data, status=200):
        body = json.dumps(data, ensure_ascii=False, default=str).encode("utf-8")
        self._send(status, body, "application/json; charset=utf-8")

    def _error(self, exc, status=200):
        message = redact(str(exc), [self.app.cfg.feishu.app_secret,
                                    self.app.cfg.feishu.user_token,
                                    self.app.cfg.cnblogs.token])
        payload = {"ok": False, "error": message, "kind": type(exc).__name__}
        if os.environ.get("F2C_DEBUG"):
            payload["trace"] = traceback.format_exc()
        self._json(payload, status)

    def _body(self) -> dict:
        length = int(self.headers.get("Content-Length") or 0)
        if length <= 0:
            return {}
        if length > MAX_BODY:
            raise UsageError("请求体过大")
        raw = self.rfile.read(length)
        try:
            data = json.loads(raw.decode("utf-8"))
        except ValueError:
            raise UsageError("请求体不是合法 JSON")
        return data if isinstance(data, dict) else {}

    def _check_auth(self) -> bool:
        token = self.headers.get("X-Token") or ""
        if not secrets.compare_digest(token, self.app.token):
            self._json({"ok": False, "error": "会话已失效，请刷新页面"}, 403)
            return False
        origin = self.headers.get("Origin")
        if origin:
            host = self.headers.get("Host") or ""
            parsed = urllib.parse.urlsplit(origin)
            if parsed.netloc != host:
                self._json({"ok": False, "error": "拒绝跨站请求"}, 403)
                return False
        return True

    # ---- GET ----
    def do_GET(self):
        parsed = urllib.parse.urlsplit(self.path)
        path = parsed.path
        try:
            if path in ("/", "/index.html"):
                return self._static("index.html")
            if path.startswith("/static/"):
                return self._static(path[len("/static/"):])
            if path == "/api/session":
                return self._json({"ok": True, "token": self.app.token, "version": __version__})
            if path == "/api/config":
                return self._json(self.app.public_config())
            if path == "/api/history":
                return self._json(self.app.history())
            if path.startswith("/api/job/"):
                job = self.app.job(path[len("/api/job/"):])
                return self._json(dict(job, ok=True))
            if path.startswith("/api/image/"):
                token = urllib.parse.unquote(path[len("/api/image/"):])
                data, mime = self.app.media(token)
                return self._send(200, data, mime or "image/png",
                                  {"Cache-Control": "private, max-age=3600"})
            if path == "/api/check":
                doc = (urllib.parse.parse_qs(parsed.query).get("doc") or [None])[0]
                return self._json(self.app.check(doc))
            if path == "/favicon.ico":
                return self._send(204, b"", "image/x-icon")
            self._json({"ok": False, "error": "找不到该地址"}, 404)
        except AppError as exc:
            self._error(exc, 400 if isinstance(exc, UsageError) else 200)
        except Exception as exc:
            self._error(exc, 500)

    # ---- POST ----
    def do_POST(self):
        if not self._check_auth():
            return
        parsed = urllib.parse.urlsplit(self.path)
        path = parsed.path
        try:
            payload = self._body()
            if path == "/api/preview":
                ref = (payload.get("doc") or "").strip()
                if not ref:
                    raise AppError("请先填写飞书文档链接")
                return self._json(self.app.preview(ref))
            if path == "/api/publish":
                return self._json({"ok": True, "job": self.app.start_publish(payload)})
            if path == "/api/config":
                return self._json(self.app.save_config(payload))
            if path == "/api/check":
                return self._json(self.app.check((payload.get("doc") or "").strip() or None))
            if path == "/api/history/delete":
                return self._json(self.app.forgot(str(payload.get("doc_id") or "")))
            self._json({"ok": False, "error": "找不到该接口"}, 404)
        except AppError as exc:
            self._error(exc, 400 if isinstance(exc, UsageError) else 200)
        except Exception as exc:
            self._error(exc, 500)

    # ---- 静态文件 ----
    def _static(self, name: str):
        name = name or "index.html"
        safe = os.path.normpath(name).replace("\\", "/")
        if safe.startswith("..") or safe.startswith("/"):
            self._json({"ok": False, "error": "非法路径"}, 400)
            return
        full = os.path.join(WEB_DIR, safe)
        if not os.path.isfile(full):
            self._json({"ok": False, "error": "文件不存在"}, 404)
            return
        ext = os.path.splitext(full)[1].lower()
        mime = STATIC_TYPES.get(ext) or mimetypes.guess_type(full)[0] or "application/octet-stream"
        with open(full, "rb") as fh:
            data = fh.read()
        self._send(200, data, mime)


def serve(host: str = "127.0.0.1", port: int = 8766, *, open_browser: bool = True,
          config_path: str | None = None) -> None:
    try:
        sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    except Exception:
        pass

    app = App(config_path)
    Handler.app = app

    last_error = None
    for candidate in range(port, port + 12):
        try:
            httpd = ThreadingHTTPServer((host, candidate), Handler)
            break
        except OSError as exc:
            last_error = exc
            continue
    else:
        raise AppError("端口 %d~%d 都被占用了，换个端口：--port 9000" % (port, port + 11))

    url = "http://%s:%d/" % (host, httpd.server_address[1])
    print("")
    print("  飞书 → 博客园  网页版已启动")
    print("  地址：%s" % url)
    print("  配置文件：%s" % app.cfg.path)
    print("  按 Ctrl+C 停止")
    print("")
    if open_browser:
        threading.Timer(0.6, lambda: webbrowser.open(url)).start()
    try:
        httpd.serve_forever()
    except KeyboardInterrupt:
        print("\n已停止。")
    finally:
        httpd.server_close()
