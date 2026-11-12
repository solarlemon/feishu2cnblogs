"""基础工具：错误类型、日志、HTTP 客户端、JSON 读写。

只用标准库，目的是让用户拿到 .py 文件就能跑，不必配虚拟环境。
"""

from __future__ import annotations

import json
import os
import ssl
import sys
import urllib.error
import urllib.parse
import urllib.request

from . import __version__


# ---------------------------------------------------------------------------
# 错误
# ---------------------------------------------------------------------------

class AppError(Exception):
    """预期内的业务错误：消息直接展示给用户看。"""

    exit_code = 1


class UsageError(AppError):
    exit_code = 2


class NetworkError(AppError):
    exit_code = 4


class FeishuError(AppError):
    """飞书开放接口返回了非 0 的 code。"""

    def __init__(self, code, msg, *, path="", hint=""):
        self.code = code
        self.msg = msg
        self.path = path
        self.hint = hint
        text = "飞书接口报错 code=%s: %s" % (code, msg)
        if path:
            text += "（%s）" % path
        if hint:
            text += "\n提示：" + hint
        super().__init__(text)


class CnblogsError(AppError):
    """博客园 XML-RPC 返回 Fault 或响应异常。"""


# ---------------------------------------------------------------------------
# 日志
# ---------------------------------------------------------------------------

_QUIET = False


def set_quiet(quiet: bool) -> None:
    global _QUIET
    _QUIET = quiet


def info(message: str) -> None:
    if not _QUIET:
        print(message, file=sys.stderr)


def warn(message: str) -> None:
    if not _QUIET:
        print("⚠ " + message, file=sys.stderr)


def fail(message: str) -> None:
    print("✗ " + message, file=sys.stderr)


# ---------------------------------------------------------------------------
# JSON 文件
# ---------------------------------------------------------------------------

def read_json(path, default=None):
    try:
        with open(path, "r", encoding="utf-8") as fh:
            return json.load(fh)
    except FileNotFoundError:
        return default
    except (OSError, ValueError) as exc:
        raise UsageError("读取 %s 失败：%s" % (path, exc))


def write_json(path, data) -> None:
    """原子写入，权限尽量收到 600（里面可能有 App Secret / 令牌）。"""
    path = str(path)
    parent = os.path.dirname(path)
    if parent:
        os.makedirs(parent, exist_ok=True)
    tmp = path + ".tmp"
    payload = json.dumps(data, ensure_ascii=False, indent=2) + "\n"
    with open(tmp, "w", encoding="utf-8") as fh:
        fh.write(payload)
    try:
        os.chmod(tmp, 0o600)
    except (OSError, NotImplementedError):
        pass
    os.replace(tmp, path)


# ---------------------------------------------------------------------------
# HTTP
# ---------------------------------------------------------------------------

class HttpResponse:
    def __init__(self, status, headers, body, url):
        self.status = status
        self.headers = headers
        self.body = body
        self.url = url

    @property
    def text(self) -> str:
        return self.body.decode("utf-8", errors="replace")

    def json(self):
        try:
            return json.loads(self.text)
        except ValueError:
            raise NetworkError("服务端返回的不是 JSON：%s" % self.text[:300])


def http_request(
    method: str,
    url: str,
    *,
    headers=None,
    body: bytes | None = None,
    timeout: float = 60,
    max_redirects: int = 5,
    max_bytes: int | None = None,
) -> HttpResponse:
    """发一个请求，手动跟随重定向（飞书媒体下载会 302 到签名地址）。"""
    request_headers = {
        "User-Agent": "feishu2cnblogs/%s (+python-urllib)" % __version__,
        "Accept": "*/*",
    }
    if headers:
        request_headers.update(headers)

    current_url = url
    for _ in range(max_redirects + 1):
        req = urllib.request.Request(
            current_url,
            data=body,
            headers=request_headers,
            method=method,
        )
        try:
            with urllib.request.urlopen(req, timeout=timeout) as resp:
                data = resp.read() if max_bytes is None else resp.read(max_bytes)
                return HttpResponse(resp.status, dict(resp.headers.items()), data, current_url)
        except urllib.error.HTTPError as exc:
            if exc.code in (301, 302, 303, 307, 308):
                location = exc.headers.get("Location")
                if not location:
                    raise NetworkError("重定向缺少 Location：%s" % current_url)
                current_url = urllib.parse.urljoin(current_url, location)
                if exc.code == 303:
                    method, body = "GET", None
                continue
            detail = ""
            try:
                detail = exc.read().decode("utf-8", errors="replace")[:500]
            except Exception:
                pass
            raise NetworkError(
                "HTTP %s 请求失败：%s\n%s" % (exc.code, current_url, detail)
            )
        except urllib.error.URLError as exc:
            raise NetworkError("网络错误：%s（%s）" % (exc.reason, current_url))
        except (TimeoutError, OSError) as exc:
            raise NetworkError("网络异常：%s（%s）" % (exc, current_url))
        except ValueError as exc:
            raise NetworkError("请求地址不合法：%s（%s）" % (exc, current_url))
    raise NetworkError("重定向次数过多：%s" % url)


def ssl_context() -> ssl.SSLContext:
    return ssl.create_default_context()


def redact(text: str, secrets) -> str:
    """把凭据从输出里抹掉，避免贴日志时泄露。"""
    if not text:
        return text
    for secret in secrets:
        if secret and len(str(secret)) >= 4:
            text = text.replace(str(secret), "***")
    return text
