"""网页层测试：用假 App 起一个真实 HTTP 服务，覆盖路由、鉴权、静态资源 MIME、错误处理。

不联网、不需要飞书/博客园凭据。
"""

from __future__ import annotations

import json
import os
import sys
import threading
import unittest
import urllib.error
import urllib.request
from http.server import ThreadingHTTPServer

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from feishu2cnblogs import webapp  # noqa: E402
from feishu2cnblogs.util import AppError  # noqa: E402


class StubApp(webapp.App):
    def __init__(self, config_path=None):
        super().__init__(config_path)
        self.published = []

    def public_config(self):
        return {
            "ok": True, "version": "test", "config_path": "/tmp/config.json",
            "state_path": "/tmp/state.json",
            "feishu": {"app_id": "cli_x", "app_secret": "ab••cd", "ready": True,
                       "has_secret": True, "user_token": "", "has_user_token": False,
                       "base_url": "https://open.feishu.cn"},
            "cnblogs": {"username": "demo", "blog": "demo", "token": "to••en", "ready": True,
                        "has_token": True, "categories": [], "tags": [],
                        "markdown_category": "[Markdown]"},
        }

    def preview(self, ref):
        if "broken" in ref:
            raise AppError("文档不存在的测试错误")
        return {
            "ok": True, "doc_id": "DOC1", "doc_title": "测试文档", "title": "测试文档",
            "markdown": "# 标题\n\n正文", "preview": "# 标题\n\n正文",
            "blocks": 3, "chars": 8, "images": 0, "warnings": ["示例警告"],
            "meta": {}, "existing": None, "defaults": {"categories": [], "tags": []},
        }

    def media(self, token):
        return b"\x89PNG\r\n\x1a\n", "image/png"

    def history(self):
        return {"ok": True, "state_path": "x", "items": [
            {"doc_id": "DOC1", "post_id": "1", "title": "测试文档", "url": "https://x/1",
             "draft": True, "updated_at": "2026-01-01T00:00:00+08:00"},
        ]}

    def start_publish(self, payload):
        self.published.append(payload)
        job_id = "job1"
        self.jobs[job_id] = {
            "id": job_id, "status": "done", "progress": 100, "message": "发布完成",
            "logs": [{"p": 100, "m": "发布完成", "t": 0.1}],
            "result": {"action": "created", "post_id": "9", "title": "测试文档",
                       "url": "https://x/9", "draft": True, "warnings": [], "stats": {}},
            "error": None, "started_at": 0,
        }
        return job_id


class TestWebLayer(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.orig_app = webapp.Handler.app
        webapp.Handler.app = StubApp(None)
        cls.token = webapp.Handler.app.token
        cls.httpd = ThreadingHTTPServer(("127.0.0.1", 0), webapp.Handler)
        cls.port = cls.httpd.server_address[1]
        cls.thread = threading.Thread(target=cls.httpd.serve_forever, daemon=True)
        cls.thread.start()

    @classmethod
    def tearDownClass(cls):
        cls.httpd.shutdown()
        cls.httpd.server_close()
        webapp.Handler.app = cls.orig_app

    def request(self, path, *, payload=None, token=None, origin=None, method=None):
        data = None
        headers = {}
        if payload is not None:
            data = json.dumps(payload).encode()
            headers["Content-Type"] = "application/json"
        if token:
            headers["X-Token"] = token
        if origin:
            headers["Origin"] = origin
        req = urllib.request.Request(
            "http://127.0.0.1:%d%s" % (self.port, path),
            data=data, headers=headers, method=method or ("POST" if data else "GET"))
        try:
            with urllib.request.urlopen(req, timeout=10) as resp:
                return resp.status, resp.headers, resp.read()
        except urllib.error.HTTPError as exc:
            return exc.code, exc.headers, exc.read()

    # ---- 静态资源 ----
    def test_index_served(self):
        status, headers, body = self.request("/")
        self.assertEqual(status, 200)
        self.assertIn("text/html", headers["Content-Type"])
        self.assertIn("飞书".encode("utf-8"), body)

    def test_js_has_javascript_mime(self):
        # Windows 注册表会把 .js 映射成 text/plain，必须由服务端纠正，否则浏览器拒绝执行
        for path in ("/static/app.js", "/static/markdown.js"):
            status, headers, body = self.request(path)
            self.assertEqual(status, 200)
            self.assertIn("javascript", headers["Content-Type"])
            self.assertGreater(len(body), 1000)

    def test_css_mime(self):
        status, headers, _ = self.request("/static/style.css")
        self.assertEqual(status, 200)
        self.assertIn("text/css", headers["Content-Type"])

    def test_missing_asset_404(self):
        status, _, body = self.request("/static/nope.js")
        self.assertEqual(status, 404)
        self.assertFalse(json.loads(body)["ok"])

    def test_path_traversal_blocked(self):
        status, _, _ = self.request("/static/../webapp.py")
        self.assertIn(status, (400, 404))

    # ---- 鉴权 ----
    def test_session_token(self):
        status, _, body = self.request("/api/session")
        self.assertEqual(status, 200)
        self.assertTrue(json.loads(body)["token"])

    def test_post_requires_token(self):
        status, _, body = self.request("/api/preview", payload={"doc": "x"})
        self.assertEqual(status, 403)
        self.assertIn("会话已失效", json.loads(body)["error"])

    def test_cross_origin_rejected(self):
        status, _, _ = self.request("/api/preview", payload={"doc": "x"},
                                    token=self.token, origin="http://evil.example")
        self.assertEqual(status, 403)

    def test_same_origin_allowed(self):
        host = "127.0.0.1:%d" % self.port
        status, _, body = self.request("/api/preview", payload={"doc": "x"},
                                       token=self.token, origin="http://" + host)
        self.assertEqual(status, 200)
        self.assertTrue(json.loads(body)["ok"])

    # ---- 业务接口 ----
    def test_config(self):
        status, _, body = self.request("/api/config")
        data = json.loads(body)
        self.assertEqual(status, 200)
        self.assertTrue(data["feishu"]["ready"])
        # 凭据只以掩码形式出现，且带 has_* 标记
        self.assertIn("••", data["feishu"]["app_secret"])
        self.assertTrue(data["feishu"]["has_secret"])
        self.assertIn("••", data["cnblogs"]["token"])

    def test_preview_ok(self):
        status, _, body = self.request("/api/preview", payload={"doc": "doc1"}, token=self.token)
        data = json.loads(body)
        self.assertEqual(status, 200)
        self.assertEqual(data["doc_title"], "测试文档")
        self.assertEqual(data["warnings"], ["示例警告"])

    def test_preview_error_is_json(self):
        status, _, body = self.request("/api/preview", payload={"doc": "broken"}, token=self.token)
        data = json.loads(body)
        self.assertEqual(status, 200)
        self.assertFalse(data["ok"])
        self.assertIn("文档不存在", data["error"])

    def test_preview_empty_doc(self):
        status, _, body = self.request("/api/preview", payload={"doc": ""}, token=self.token)
        self.assertFalse(json.loads(body)["ok"])

    def test_publish_returns_job(self):
        status, _, body = self.request("/api/publish", payload={"doc": "doc1", "publish": False},
                                       token=self.token)
        data = json.loads(body)
        self.assertEqual(status, 200)
        self.assertEqual(data["job"], "job1")

    def test_job_polling(self):
        self.request("/api/publish", payload={"doc": "doc1"}, token=self.token)
        status, _, body = self.request("/api/job/job1")
        data = json.loads(body)
        self.assertEqual(status, 200)
        self.assertTrue(data["ok"])
        self.assertEqual(data["status"], "done")
        self.assertEqual(data["result"]["post_id"], "9")

    def test_unknown_job(self):
        status, _, body = self.request("/api/job/nope")
        self.assertFalse(json.loads(body)["ok"])

    def test_history(self):
        status, _, body = self.request("/api/history")
        data = json.loads(body)
        self.assertEqual(status, 200)
        self.assertEqual(len(data["items"]), 1)

    def test_media_proxy(self):
        status, headers, body = self.request("/api/image/TOKEN")
        self.assertEqual(status, 200)
        self.assertIn("image/png", headers["Content-Type"])
        self.assertTrue(body.startswith(b"\x89PNG"))

    def test_unknown_route(self):
        status, _, body = self.request("/api/nope")
        self.assertEqual(status, 404)

    def test_bad_json_body(self):
        req = urllib.request.Request(
            "http://127.0.0.1:%d/api/preview" % self.port,
            data=b"{not json", headers={"X-Token": self.token,
                                        "Content-Type": "application/json"},
            method="POST")
        with self.assertRaises(urllib.error.HTTPError) as ctx:
            urllib.request.urlopen(req, timeout=10)
        self.assertEqual(ctx.exception.code, 400)
        self.assertIn("JSON", json.loads(ctx.exception.read())["error"])


class TestCliEntry(unittest.TestCase):
    def test_bare_invocation_launches_web(self):
        """不带子命令运行应直接进网页版（双击/一行命令即可）。"""
        from unittest import mock

        from feishu2cnblogs import cli

        with mock.patch("feishu2cnblogs.webapp.serve") as serve:
            code = cli.main([])
        self.assertEqual(code, 0)
        serve.assert_called_once()


if __name__ == "__main__":
    unittest.main(verbosity=2)
