"""命令行入口：python -m feishu2cnblogs <子命令>。

设计原则
    · 默认发「草稿/非公开」，公开必须显式 --publish（避免手滑把半成品推上线）
    · 凭据只存在配置文件里（权限 600），输出里一律脱敏
    · 每个子命令配 --json，方便被其他程序或定时任务调用
"""

from __future__ import annotations

import argparse
import json
import os
import sys

from . import __version__
from .blog import CnblogsClient
from .config import (
    DEFAULT_BASE_URL,
    Config,
    default_config_path,
    load_config,
    save_config,
    secrets_of,
)
from .feishu import FeishuClient, parse_document_ref
from .pipeline import PublishOptions, publish
from .state import StateStore
from .util import AppError, redact, set_quiet


# ---------------------------------------------------------------------------
# 输出工具
# ---------------------------------------------------------------------------

class Reporter:
    def __init__(self, as_json: bool):
        self.as_json = as_json

    def emit(self, payload: dict, human_lines: list) -> None:
        if self.as_json:
            print(json.dumps(payload, ensure_ascii=False, indent=2))
        else:
            for line in human_lines:
                print(line)


def _mask(value: str, keep: int = 4) -> str:
    value = value or ""
    if not value:
        return "（未设置）"
    if len(value) <= keep + 2:
        return value[:1] + "***"
    return value[:keep] + "***" + value[-2:]


def _ask(prompt: str, default: str = "", secret: bool = False) -> str:
    suffix = " [%s]" % default if default else ""
    if secret:
        suffix = " [******]" if default else ""
    try:
        value = input("%s%s: " % (prompt, suffix)).strip()
    except EOFError:
        return default
    if not value:
        return default
    return value


# ---------------------------------------------------------------------------
# init / config
# ---------------------------------------------------------------------------

def cmd_init(args, cfg: Config, reporter: Reporter) -> int:
    path = cfg.path
    print("配置将保存到：%s" % path)
    print("提示：直接回车表示保留原值；App Secret / 令牌输入时不会回显。\n")

    print("== 飞书 ==")
    feishu = cfg.feishu
    app_id = _ask("App ID", feishu.app_id)
    app_secret = feishu.app_secret
    if app_id:
        app_secret = _ask("App Secret（输入不可见）", app_secret, secret=True)
    user_token = _ask("可选：User Access Token（不填则用应用身份）", feishu.user_token, secret=True)
    base_url = _ask("飞书开放平台地址", feishu.base_url or DEFAULT_BASE_URL)

    print("\n== 博客园 ==")
    cnblogs = cfg.cnblogs
    username = _ask("登录用户名（不是昵称）", cnblogs.username)
    blog = _ask("博客名（博客地址 www.cnblogs.com/ 后面那段）", cnblogs.blog)
    token = _ask("访问令牌（后台 → 设置 → 开放 API 生成，输入不可见）", cnblogs.token, secret=True)
    categories = _ask("默认分类，逗号分隔（可留空）", ",".join(cnblogs.categories))
    tags = _ask("默认标签，逗号分隔（可留空）", ",".join(cnblogs.tags))

    cfg.feishu.app_id = app_id
    cfg.feishu.app_secret = app_secret
    cfg.feishu.user_token = user_token
    cfg.feishu.base_url = base_url or DEFAULT_BASE_URL
    cfg.cnblogs.username = username
    cfg.cnblogs.blog = blog
    cfg.cnblogs.token = token
    if categories is not None:
        cfg.cnblogs.categories = [c.strip() for c in categories.replace("，", ",").split(",") if c.strip()]
    if tags is not None:
        cfg.cnblogs.tags = [t.strip() for t in tags.replace("，", ",").split(",") if t.strip()]

    save_config(cfg)
    reporter.emit(
        {"ok": True, "config_path": cfg.path},
        ["", "✅ 已保存。接着可以运行：python -m feishu2cnblogs check"],
    )
    return 0


def cmd_config(args, cfg: Config, reporter: Reporter) -> int:
    action = args.action
    if action == "path":
        print(cfg.path)
        return 0
    if action == "show":
        data = {
            "config_path": cfg.path,
            "state_path": cfg.resolve_state_path(),
            "feishu": {
                "app_id": cfg.feishu.app_id,
                "app_secret": _mask(cfg.feishu.app_secret),
                "user_token": _mask(cfg.feishu.user_token),
                "base_url": cfg.feishu.base_url,
                "ready": cfg.feishu.ready(),
            },
            "cnblogs": {
                "username": cfg.cnblogs.username,
                "blog": cfg.cnblogs.blog,
                "token": _mask(cfg.cnblogs.token),
                "endpoint": cfg.cnblogs.api_endpoint(),
                "categories": cfg.cnblogs.categories,
                "tags": cfg.cnblogs.tags,
                "ready": cfg.cnblogs.ready(),
            },
        }
        if reporter.as_json:
            print(json.dumps(data, ensure_ascii=False, indent=2))
        else:
            print("配置文件：%s" % data["config_path"])
            print("状态文件：%s" % data["state_path"])
            print("飞书：App ID=%s  App Secret=%s  可用=%s" % (
                data["feishu"]["app_id"] or "（未设置）",
                data["feishu"]["app_secret"], "是" if data["feishu"]["ready"] else "否"))
            print("博客园：用户名=%s  博客名=%s  令牌=%s  可用=%s" % (
                data["cnblogs"]["username"] or "（未设置）",
                data["cnblogs"]["blog"] or "（未设置）",
                data["cnblogs"]["token"], "是" if data["cnblogs"]["ready"] else "否"))
            print("博客园接口：%s" % data["cnblogs"]["endpoint"])
        return 0
    if action == "set":
        return _config_set(args, cfg, reporter)
    raise AppError("未知操作：%s" % action)


def _config_set(args, cfg: Config, reporter: Reporter) -> int:
    key = (args.key or "").strip()
    value = args.value
    mapping = {
        "feishu.app_id": lambda v: setattr(cfg.feishu, "app_id", v),
        "feishu.app_secret": lambda v: setattr(cfg.feishu, "app_secret", v),
        "feishu.user_token": lambda v: setattr(cfg.feishu, "user_token", v),
        "feishu.base_url": lambda v: setattr(cfg.feishu, "base_url", v),
        "cnblogs.username": lambda v: setattr(cfg.cnblogs, "username", v),
        "cnblogs.blog": lambda v: setattr(cfg.cnblogs, "blog", v),
        "cnblogs.token": lambda v: setattr(cfg.cnblogs, "token", v),
        "cnblogs.endpoint": lambda v: setattr(cfg.cnblogs, "endpoint", v),
        "cnblogs.blog_url": lambda v: setattr(cfg.cnblogs, "blog_url", v),
        "cnblogs.categories": lambda v: setattr(
            cfg.cnblogs, "categories",
            [x.strip() for x in (v or "").replace("，", ",").split(",") if x.strip()]),
        "cnblogs.tags": lambda v: setattr(
            cfg.cnblogs, "tags",
            [x.strip() for x in (v or "").replace("，", ",").split(",") if x.strip()]),
        "cnblogs.add_ai_declaration": lambda v: setattr(
            cfg.cnblogs, "add_ai_declaration", str(v).lower() in ("1", "true", "yes", "on")),
        "cnblogs.add_source_link": lambda v: setattr(
            cfg.cnblogs, "add_source_link", str(v).lower() in ("1", "true", "yes", "on")),
        "cnblogs.max_image_mb": lambda v: setattr(cfg.cnblogs, "max_image_mb", int(v)),
    }
    if key not in mapping:
        raise AppError(
            "不认识的配置项：%s\n可用的：%s" % (key, "、".join(sorted(mapping)))
        )
    if value is None:
        raise AppError("缺少值，例如：config set cnblogs.blog my-blog")
    mapping[key](value)
    save_config(cfg)
    reporter.emit({"ok": True, "key": key}, ["✅ 已设置 %s" % key])
    return 0


# ---------------------------------------------------------------------------
# check
# ---------------------------------------------------------------------------

def cmd_check(args, cfg: Config, reporter: Reporter) -> int:
    lines = []
    ok = True
    payload = {"ok": True, "feishu": {}, "cnblogs": {}}

    # 飞书
    if not cfg.feishu.ready():
        payload["ok"] = False
        payload["feishu"] = {"ready": False, "error": cfg.feishu.missing_hint()}
        ok = False
        lines.append("✗ 飞书：未配置凭证")
    else:
        try:
            client = FeishuClient(cfg)
            if not cfg.feishu.user_token:
                client.tenant_token()
            payload["feishu"] = {
                "ready": True,
                "auth": "user_token" if cfg.feishu.user_token else "tenant_access_token",
            }
            lines.append("✓ 飞书：凭证有效（%s）" % payload["feishu"]["auth"])
            if args.doc:
                document = client.load_document(args.doc)
                payload["feishu"]["document"] = {
                    "doc_id": document["doc_id"],
                    "title": document["title"],
                    "blocks": len(document["blocks"]),
                }
                lines.append("✓ 文档可读：《%s》共 %d 个块" % (
                    document["title"], len(document["blocks"])))
        except Exception as exc:
            ok = False
            payload["ok"] = False
            payload["feishu"] = {"ready": True, "error": str(exc)}
            lines.append("✗ 飞书：%s" % exc)

    # 博客园
    if not cfg.cnblogs.ready():
        payload["ok"] = False
        payload["cnblogs"] = {"ready": False, "error": cfg.cnblogs.missing_hint()}
        ok = False
        lines.append("✗ 博客园：未配置凭据")
    else:
        try:
            client = CnblogsClient(cfg)
            result = client.check()
            blogs = [b.get("blogName") or b.get("url") or "" for b in result["blogs"]
                     if isinstance(b, dict)]
            payload["cnblogs"] = {
                "ready": True, "endpoint": result["endpoint"],
                "blogs": blogs, "categories": client.get_categories(),
            }
            lines.append("✓ 博客园：鉴权通过（%d 个博客）" % len(blogs))
            if blogs:
                lines.append("  可用博客：%s" % "、".join(x for x in blogs if x))
        except Exception as exc:
            ok = False
            payload["ok"] = False
            payload["cnblogs"] = {"ready": True, "error": str(exc)}
            lines.append("✗ 博客园：%s" % exc)

    reporter.emit(payload, lines)
    return 0 if ok else 1


# ---------------------------------------------------------------------------
# inspect / fetch
# ---------------------------------------------------------------------------

def cmd_inspect(args, cfg: Config, reporter: Reporter) -> int:
    feishu = FeishuClient(cfg)
    document = feishu.load_document(args.doc)
    if args.dump_blocks:
        with open(args.dump_blocks, "w", encoding="utf-8") as fh:
            json.dump(document, fh, ensure_ascii=False, indent=2)
        print("原始块结构已写入：%s" % args.dump_blocks)

    from .converter import BlockConverter
    result = BlockConverter().convert(document)
    types = {}
    for block in document["blocks"]:
        types[block.get("block_type")] = types.get(block.get("block_type"), 0) + 1
    payload = {
        "doc_id": document["doc_id"],
        "title": result.title,
        "blocks": len(document["blocks"]),
        "block_types": {str(k): v for k, v in sorted(types.items(), key=lambda kv: str(kv[0]))},
        "markdown_chars": len(result.markdown),
        "images": len(result.images.items),
        "warnings": result.warnings,
    }
    lines = [
        "标题：《%s》" % result.title,
        "doc_id：%s" % document["doc_id"],
        "块数：%d，图片：%d，Markdown %d 字" % (
            payload["blocks"], payload["images"], payload["markdown_chars"]),
        "块类型分布：%s" % ", ".join("%s×%d" % (k, v) for k, v in payload["block_types"].items()),
    ]
    for warning in result.warnings:
        lines.append("⚠ " + warning)
    reporter.emit(payload, lines)
    return 0


def cmd_fetch(args, cfg: Config, reporter: Reporter) -> int:
    feishu = FeishuClient(cfg)
    document = feishu.load_document(args.doc)
    out = args.out
    if not out:
        from .feishu import safe_filename
        out = os.path.join(args.output_dir, safe_filename(document["title"]) + ".md")
    from .converter import BlockConverter
    result = BlockConverter().convert(document)

    markdown = result.markdown
    warnings = list(result.warnings)
    if args.download_images:
        from .converter import collect_image_tokens, replace_image_placeholders
        tokens = collect_image_tokens(markdown)
        base = os.path.dirname(os.path.abspath(out))
        folder = os.path.join(base, "assets")
        os.makedirs(folder, exist_ok=True)
        mapping = {}
        for index, token in enumerate(tokens, 1):
            image = result.images.items.get(token)
            name = image.name if image else "image-%d.png" % index
            try:
                data, _mime = feishu.download_media(token)
                filename = "%02d-%s" % (index, "".join(ch if ch.isalnum() or ch in ".-_" else "_" for ch in name))
                with open(os.path.join(folder, filename), "wb") as fh:
                    fh.write(data)
                mapping[token] = os.path.relpath(os.path.join(folder, filename), base).replace("\\", "/")
            except Exception as exc:
                warnings.append("图片下载失败（%s）：%s" % (name, exc))
        markdown = replace_image_placeholders(markdown, mapping)

    parent = os.path.dirname(os.path.abspath(out))
    if parent:
        os.makedirs(parent, exist_ok=True)
    with open(out, "w", encoding="utf-8", newline="\n") as fh:
        fh.write(markdown)

    payload = {
        "ok": True, "doc_id": document["doc_id"], "title": result.title,
        "out": os.path.abspath(out), "images": len(result.images.items),
        "warnings": warnings,
    }
    lines = [
        "✅ 已导出《%s》" % result.title,
        "文件：%s" % payload["out"],
        "图片：%d 张%s" % (payload["images"], "（已下载到同目录 assets）" if args.download_images else "（保留占位符）"),
    ]
    for warning in warnings:
        lines.append("⚠ " + warning)
    reporter.emit(payload, lines)
    return 0


# ---------------------------------------------------------------------------
# publish
# ---------------------------------------------------------------------------

def cmd_publish(args, cfg: Config, reporter: Reporter) -> int:
    if not cfg.cnblogs.ready():
        raise AppError(cfg.cnblogs.missing_hint())

    options = PublishOptions(
        categories=[x.strip() for x in (args.categories or "").replace("，", ",").split(",") if x.strip()],
        tags=[x.strip() for x in (args.tags or "").replace("，", ",").split(",") if x.strip()],
        title=args.title,
        draft=not args.publish,
        publish=args.publish,
        force_new=args.new,
        upload_images=not args.no_images,
        ai_declaration=args.ai_declaration or cfg.cnblogs.add_ai_declaration,
        source_link=args.source_link or cfg.cnblogs.add_source_link,
        excerpt=args.summary,
    )

    result = publish(cfg, args.doc, options, local_path=args.save_md)

    payload = {
        "ok": True,
        "action": result.action,
        "doc_id": result.doc_id,
        "post_id": result.post_id,
        "title": result.title,
        "url": result.url,
        "draft": result.draft,
        "warnings": result.warnings,
        "stats": result.stats,
    }
    lines = [
        "✅ %s《%s》" % (
            "已创建" if result.action == "created" else "已更新", result.title),
        "文章 ID：%s" % result.post_id,
        "链接：%s" % result.url,
        "状态：%s" % ("草稿/非公开（加 --publish 可公开）" if result.draft else "已公开发布"),
    ]
    if result.stats:
        lines.append("统计：%d 块 / %d 张图 / %d 字" % (
            result.stats.get("blocks", 0), result.stats.get("images", 0),
            result.stats.get("chars", 0)))
    for warning in result.warnings:
        lines.append("⚠ " + warning)
    if result.draft:
        lines.append("查看草稿：登录博客园后台 → 随笔 → 草稿箱")
    reporter.emit(payload, lines)
    return 0


# ---------------------------------------------------------------------------
# list / forget / upload
# ---------------------------------------------------------------------------

def cmd_list(args, cfg: Config, reporter: Reporter) -> int:
    store = StateStore(cfg.resolve_state_path())
    items = store.all()
    payload = {"ok": True, "count": len(items), "state_path": store.path, "items": items}
    lines = ["已发布记录（%d）：" % len(items)]
    for item in items:
        lines.append("  %s  %s  %s" % (
            item.get("post_id", ""), item.get("title", ""), item.get("url", "")))
    if not items:
        lines.append("  还没有发布记录。先运行 publish。")
    reporter.emit(payload, lines)
    return 0


def cmd_forget(args, cfg: Config, reporter: Reporter) -> int:
    store = StateStore(cfg.resolve_state_path())
    if args.all:
        removed = len(store.posts)
        store.data["posts"] = {}
        store.save()
        if getattr(args, "remove_config", False) and os.path.exists(cfg.path):
            os.remove(cfg.path)
            print("已删除配置文件：%s" % cfg.path)
        reporter.emit({"ok": True, "removed": removed}, ["已清空发布记录 %d 条" % removed])
        return 0
    if not args.doc:
        raise AppError("请指定 --doc 或 --all")
    parsed = parse_document_ref(args.doc)
    removed = store.remove(parsed["token"])
    if removed:
        store.save()
    reporter.emit({"ok": True, "removed": 1 if removed else 0},
                  ["已移除记录：%s" % args.doc if removed else "没有找到这条记录"])
    return 0


def cmd_upload(args, cfg: Config, reporter: Reporter) -> int:
    if not cfg.cnblogs.ready():
        raise AppError(cfg.cnblogs.missing_hint())
    blog = CnblogsClient(cfg)
    results = []
    for path in args.files:
        if not os.path.isfile(path):
            raise AppError("文件不存在：%s" % path)
        with open(path, "rb") as fh:
            data = fh.read()
        url = blog.upload_media(data, os.path.basename(path))
        results.append({"file": path, "url": url})
        print("%s → %s" % (path, url))
    reporter.emit({"ok": True, "items": results}, [])
    return 0


def cmd_categories(args, cfg: Config, reporter: Reporter) -> int:
    if not cfg.cnblogs.ready():
        raise AppError(cfg.cnblogs.missing_hint())
    blog = CnblogsClient(cfg)
    names = blog.get_categories()
    reporter.emit({"ok": True, "categories": names},
                  ["博客园分类（%d）：\n  %s" % (len(names), "\n  ".join(names)) if names
                   else "没有读到分类（可能接口不支持，或博客还没有分类）"])
    return 0


def cmd_web(args, cfg: Config, reporter: Reporter) -> int:
    from .webapp import serve

    serve(
        host=args.host,
        port=args.port,
        open_browser=not args.no_browser,
        config_path=cfg.path,
    )
    return 0

# ---------------------------------------------------------------------------
# 参数解析
# ---------------------------------------------------------------------------

def _add_common(sub, *, needs_json=True):
    if needs_json:
        sub.add_argument("--json", action="store_true", default=argparse.SUPPRESS,
                         help="以 JSON 输出结果")


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="feishu2cnblogs",
        description="把飞书云文档（docx / wiki）转换并发布到博客园。",
        epilog="示例：\n"
               "  python -m feishu2cnblogs web              # 打开网页版（最方便）\n"
               "  python -m feishu2cnblogs init\n"
               "  python -m feishu2cnblogs check --doc https://xxx.feishu.cn/docx/XXXX\n"
               "  python -m feishu2cnblogs publish https://xxx.feishu.cn/docx/XXXX --tags 飞书,工具\n"
               "  python -m feishu2cnblogs publish https://xxx.feishu.cn/docx/XXXX --publish\n",
        formatter_class=argparse.RawDescriptionHelpFormatter,
    )
    parser.add_argument("--version", action="version", version="%(prog)s " + __version__)
    parser.add_argument("--config", help="配置文件路径（默认 ~/.feishu2cnblogs/config.json）")
    parser.add_argument("-q", "--quiet", action="store_true", help="不输出过程日志")
    parser.add_argument("--json", action="store_true", help="以 JSON 输出结果")

    subs = parser.add_subparsers(dest="command", required=True)

    sub = subs.add_parser("init", help="交互式填写飞书和博客园凭据")
    _add_common(sub)

    sub = subs.add_parser("config", help="查看 / 修改配置")
    _add_common(sub)
    sub.add_argument("action", choices=["show", "path", "set"])
    sub.add_argument("key", nargs="?", help="配置项，如 cnblogs.blog")
    sub.add_argument("value", nargs="?", help="配置值")

    sub = subs.add_parser("check", help="检查飞书和博客园两边是否连通")
    _add_common(sub)
    sub.add_argument("--doc", help="顺便验证某篇文档是否可读")

    sub = subs.add_parser("inspect", help="查看文档结构（块数 / 类型 / 警告）")
    _add_common(sub)
    sub.add_argument("doc")
    sub.add_argument("--dump-blocks", help="把飞书原始块结构 dump 成 JSON，便于排查")

    sub = subs.add_parser("fetch", help="把文档导出成本地 Markdown（不发布）")
    _add_common(sub)
    sub.add_argument("doc")
    sub.add_argument("-o", "--out", help="输出 .md 路径")
    sub.add_argument("--output-dir", default=".", help="只给目录时按标题生成文件名")
    sub.add_argument("--download-images", action="store_true", help="把图片下载到同目录 assets/")

    sub = subs.add_parser("publish", help="转换并发布到博客园（默认存草稿）")
    _add_common(sub)
    sub.add_argument("doc", help="飞书文档链接或 token")
    sub.add_argument("--title", help="自定义标题（默认用文档标题）")
    sub.add_argument("--categories", help="分类，逗号分隔（自动补 [Markdown]）")
    sub.add_argument("--tags", help="标签，逗号分隔")
    sub.add_argument("--summary", help="摘要（默认从正文自动截取）")
    sub.add_argument("--publish", action="store_true",
                     help="公开发布（默认只存草稿/非公开）")
    sub.add_argument("--new", action="store_true",
                     help="即使之前发过也新建一篇（默认更新原文章）")
    sub.add_argument("--no-images", action="store_true", help="不把图片传到博客园图床")
    sub.add_argument("--ai-declaration", action="store_true", help="正文顶部加 AI 生成声明")
    sub.add_argument("--source-link", action="store_true", help="正文末尾附飞书原文链接")
    sub.add_argument("--save-md", help="顺便把最终 Markdown 存一份到本地")

    sub = subs.add_parser("web", help="启动本地网页版（推荐，浏览器里预览和发布）")
    _add_common(sub)
    sub.add_argument("--port", type=int, default=8766, help="端口，默认 8766")
    sub.add_argument("--host", default="127.0.0.1", help="监听地址，默认只允许本机")
    sub.add_argument("--no-browser", action="store_true", help="不自动打开浏览器")

    sub = subs.add_parser("upload", help="把本地图片上传到博客园图床")
    _add_common(sub)
    sub.add_argument("files", nargs="+")

    sub = subs.add_parser("categories", help="列出博客园分类")
    _add_common(sub)

    sub = subs.add_parser("list", help="查看已发布记录")
    _add_common(sub)

    sub = subs.add_parser("forget", help="删除某条发布记录（或全部）")
    _add_common(sub)
    sub.add_argument("--doc", help="飞书文档链接或 token")
    sub.add_argument("--all", action="store_true", help="清空所有记录")
    sub.add_argument("--remove-config", action="store_true",
                     help="与 --all 同用时删掉配置文件")

    return parser


def main(argv=None) -> int:
    if argv is None:
        argv = sys.argv[1:]
    # 不带任何参数时直接进网页版：双击、或在终端敲一行就能用
    if not argv:
        argv = ["web"]

    parser = build_parser()
    args = parser.parse_args(argv)
    as_json = getattr(args, "json", False)
    set_quiet(args.quiet)
    reporter = Reporter(as_json)

    try:
        cfg = load_config(args.config)
    except AppError as exc:
        print("✗ %s" % exc, file=sys.stderr)
        return exc.exit_code

    handlers = {
        "init": cmd_init,
        "config": cmd_config,
        "check": cmd_check,
        "inspect": cmd_inspect,
        "fetch": cmd_fetch,
        "publish": cmd_publish,
        "web": cmd_web,
        "upload": cmd_upload,
        "categories": cmd_categories,
        "list": cmd_list,
        "forget": cmd_forget,
    }
    handler = handlers[args.command]

    try:
        return handler(args, cfg, reporter)
    except AppError as exc:
        message = redact(str(exc), secrets_of(cfg))
        if as_json:
            print(json.dumps({"ok": False, "error": message}, ensure_ascii=False))
        else:
            print("✗ %s" % message, file=sys.stderr)
        return exc.exit_code
    except KeyboardInterrupt:
        print("\n已取消。", file=sys.stderr)
        return 130
    except Exception as exc:  # 兜底：不打印堆栈里的凭据
        message = redact("%s: %s" % (type(exc).__name__, exc), secrets_of(cfg))
        if as_json:
            print(json.dumps({"ok": False, "error": message}, ensure_ascii=False))
        else:
            print("✗ 未预期错误：%s" % message, file=sys.stderr)
            print("  加 -q 关闭日志，或用 --json 查看结构化输出。", file=sys.stderr)
        return 1


if __name__ == "__main__":
    sys.exit(main())
