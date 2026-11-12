"""网页版 API 冒烟测试：在本地已启动的服务上跑一遍主要端点。"""

import json
import sys
import urllib.error
import urllib.request

BASE = sys.argv[1] if len(sys.argv) > 1 else "http://127.0.0.1:8791"


def get(path):
    try:
        with urllib.request.urlopen(BASE + path, timeout=8) as resp:
            return resp.status, resp.read()
    except urllib.error.HTTPError as exc:
        return exc.code, exc.read()


def get_with_headers(path):
    try:
        with urllib.request.urlopen(BASE + path, timeout=8) as resp:
            return resp.status, resp.headers, resp.read()
    except urllib.error.HTTPError as exc:
        return exc.code, exc.headers, exc.read()


def post(path, payload, token=None, origin=None):
    data = json.dumps(payload).encode()
    req = urllib.request.Request(BASE + path, data=data, method="POST")
    req.add_header("Content-Type", "application/json")
    if token:
        req.add_header("X-Token", token)
    if origin:
        req.add_header("Origin", origin)
    try:
        with urllib.request.urlopen(req, timeout=8) as resp:
            return resp.status, resp.read()
    except urllib.error.HTTPError as exc:
        return exc.code, exc.read()


def show(label, ok, extra=""):
    print(("%-32s %s %s" % (label, "PASS" if ok else "FAIL", extra)).rstrip())
    if not ok:
        raise SystemExit(1)


code, body = get("/api/session")
token = json.loads(body)["token"]
show("GET /api/session", code == 200 and bool(token), "token=%d chars" % len(token))

for path, kind in (("/", "text/html"), ("/static/app.js", "javascript"),
                   ("/static/markdown.js", "javascript"), ("/static/style.css", "text/css")):
    code, body = get(path)
    show("GET " + path, code == 200 and len(body) > 500,
         "%d bytes" % len(body))

code, headers, body = get_with_headers("/static/app.js")
show("JS 的 Content-Type 可执行", "javascript" in headers.get("Content-Type", ""),
     headers.get("Content-Type", ""))

code, body = get("/api/config")
cfg = json.loads(body)
show("GET /api/config", code == 200 and "feishu" in cfg,
     "feishu.ready=%s cnblogs.ready=%s" % (cfg["feishu"]["ready"], cfg["cnblogs"]["ready"]))

code, body = post("/api/preview", {"doc": "https://x.feishu.cn/docx/abc"})
show("POST /api/preview 无 token 应 403", code == 403, json.loads(body)["error"])

code, body = post("/api/preview", {"doc": "https://x.feishu.cn/docx/abc"}, token=token)
data = json.loads(body)
show("POST /api/preview 有 token", code == 200 and data["ok"] is False,
     (data.get("error") or "")[:30].replace("\n", " "))

code, body = post("/api/preview", {"doc": "https://x.feishu.cn/docx/abc"},
                  token=token, origin="http://evil.example")
show("POST 跨站 Origin 应 403", code == 403, json.loads(body)["error"])

code, body = post("/api/config", {"cnblogs": {"blog": "demo-blog"}}, token=token)
show("POST /api/config 保存", code == 200 and json.loads(body)["cnblogs"]["blog"] == "demo-blog")

code, body = get("/api/history")
show("GET /api/history", code == 200 and "items" in json.loads(body))

code, body = get("/api/check")
check = json.loads(body)
show("GET /api/check", code == 200 and check["ok"] is False,
     "两侧均未配置，符合预期")

code, body = get("/api/nope")
show("GET 不存在的接口 404", code == 404)

code, body = get("/static/../webapp.py")
show("路径穿越被挡", code in (400, 404), "status=%d" % code)

print("\n全部通过")
