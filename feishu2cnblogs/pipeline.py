"""从飞书取文档 → 转 Markdown → 处理图片 → 发布/更新到博客园。

这里把三步串起来，并维护本地状态，保证：
  · 同一个飞书文档重复发布 = 更新同一篇博客，不会重复建文
  · 图片先下载再传到博客园图床，正文里不留会过期的飞书链接
  · 任何一步失败都给出可执行的下一步，而不是丢掉半篇内容
"""

from __future__ import annotations

import os
import re
from dataclasses import dataclass, field

from .blog import CnblogsClient
from .config import Config
from .converter import (
    BlockConverter,
    ConversionResult,
    ImageRegistry,
    collect_image_tokens,
    make_excerpt,
    replace_image_placeholders,
)
from .feishu import FeishuClient
from .state import ImageUploader, StateStore, content_hash
from .util import AppError, UsageError, info, warn

AI_DECLARATION = "> **说明**：本文由 AI 辅助整理，请自行甄别。\n\n"


@dataclass
class PublishOptions:
    categories: list = field(default_factory=list)
    tags: list = field(default_factory=list)
    title: str | None = None
    draft: bool = True
    publish: bool = False
    force_new: bool = False
    upload_images: bool = True
    ai_declaration: bool = False
    source_link: bool = False
    excerpt: str | None = None


@dataclass
class PublishResult:
    doc_id: str
    title: str
    post_id: str
    url: str
    action: str            # created | updated
    draft: bool
    markdown: str
    warnings: list
    stats: dict


# ---------------------------------------------------------------------------
# 读 + 转
# ---------------------------------------------------------------------------

def load_document(cfg: Config, ref: str) -> tuple:
    """返回 (FeishuClient, 文档 dict, ConversionResult)。"""
    client = FeishuClient(cfg)
    document = client.load_document(ref)
    converter = BlockConverter()
    result = converter.convert(document)
    return client, document, result


def parse_meta_block(markdown: str) -> tuple[dict, str]:
    """解析正文顶部的简易元信息块。

        <!--
        tags: 飞书, 博客
        categories: 工具
        -->

    只认注释块，避免和正文里的 HTML 冲突。
    """
    match = re.match(r"^\s*<!--\s*\n(.*?)\n\s*-->\s*\n", markdown or "", flags=re.S)
    if not match:
        return {}, markdown
    meta = {}
    for line in match.group(1).splitlines():
        if ":" not in line:
            continue
        key, _, value = line.partition(":")
        key = key.strip().lower()
        items = [item.strip() for item in re.split(r"[,，]", value) if item.strip()]
        if not items:
            continue
        if key in ("category", "categories"):
            meta["categories"] = items
        elif key in ("tag", "tags"):
            meta["tags"] = items
        elif key in ("title",):
            meta["title"] = items[0]
        elif key in ("summary", "excerpt", "description"):
            meta["excerpt"] = " ".join(items)
    return meta, markdown[match.end():]


def _apply_image_placeholders(markdown, result: ConversionResult, options, uploader,
                              progress=None) -> str:
    tokens = collect_image_tokens(markdown)
    if not tokens:
        return markdown
    if not options.upload_images:
        warn("已关闭图片上传，正文里会保留飞书图片占位符（<feishu-img://…>）。")
        return markdown
    info("开始上传 %d 张图片到博客园图床…" % len(tokens))
    if progress:
        progress(30, "开始上传 %d 张图片到博客园图床…" % len(tokens))

    def on_image(index, total, message):
        if progress:
            progress(30 + int(55 * index / max(total, 1)), message)

    mapping = uploader.upload_tokens(tokens, result.images, on_image=on_image)
    return replace_image_placeholders(markdown, mapping)


# ---------------------------------------------------------------------------
# 发布
# ---------------------------------------------------------------------------

def publish(
    cfg: Config,
    ref: str,
    options: PublishOptions,
    *,
    store: StateStore | None = None,
    local_path: str | None = None,
    progress=None,
) -> PublishResult:
    """progress(percent: int, message: str) 可选，用于网页版实时进度。"""

    def emit(percent, message):
        if progress:
            progress(percent, message)

    if not options.publish and not options.draft:
        raise UsageError("至少要指定 draft 或 publish 之一")
    if not cfg.cnblogs.ready():
        raise AppError(cfg.cnblogs.missing_hint())

    emit(3, "正在读取飞书文档…")
    info("读取飞书文档：%s" % ref)
    feishu, document, result = load_document(cfg, ref)
    doc_id = document["doc_id"]
    emit(25, "已获取 %d 个内容块，正在转换为 Markdown…" % len(document["blocks"]))

    meta, body = parse_meta_block(result.markdown)
    title = (options.title or meta.get("title") or result.title or "").strip()
    if not title:
        raise AppError("没能确定文章标题，请用 --title 指定。")
    body = body.strip("\n") + "\n"

    categories = options.categories or meta.get("categories") or cfg.cnblogs.categories
    tags = options.tags or meta.get("tags") or cfg.cnblogs.tags
    categories = list(dict.fromkeys([c for c in categories if c]))
    tags = list(dict.fromkeys([t for t in tags if t]))

    md_category = cfg.cnblogs.markdown_category or "[Markdown]"
    if not any(c.lower() == md_category.lower() for c in categories):
        categories.append(md_category)

    warnings = list(result.warnings)

    blog = CnblogsClient(cfg)
    uploader = ImageUploader(feishu, blog, max_mb=cfg.cnblogs.max_image_mb)
    body = _apply_image_placeholders(body, result, options, uploader, progress)
    warnings.extend(uploader.warnings)
    emit(86, "图片处理完成，正在整理正文…")

    if options.ai_declaration:
        body = AI_DECLARATION + body
    if options.source_link:
        body = body.rstrip("\n") + "\n\n---\n\n> 原文：[%s](%s)\n" % (
            document.get("title") or title, document.get("source") or ref)

    excerpt = options.excerpt or meta.get("excerpt") or ""
    if not excerpt:
        excerpt = make_excerpt(body)

    post = {
        "title": title,
        "description": body,
        "categories": categories,
        "mt_keywords": ",".join(tags) if tags else "",
        "mt_allow_comments": 1,
    }
    if excerpt:
        post["mt_excerpt"] = excerpt

    store = store or StateStore(cfg.resolve_state_path())
    existing = store.get(doc_id) if store else None
    publish_flag = bool(options.publish)

    emit(90, "正在写入博客园…")
    if existing and not options.force_new:
        post_id = str(existing["post_id"])
        info("这个文档之前发布过（文章 ID %s），按更新处理。" % post_id)
        blog.edit_post(post_id, post, publish=publish_flag)
        action = "updated"
    else:
        post_id = blog.new_post(post, publish=publish_flag)
        action = "created"

    emit(96, "已保存，正在读取文章链接…")
    try:
        fetched = blog.get_post(post_id)
        url = blog.post_url(post_id, fetched)
    except Exception:
        url = cfg.cnblogs.post_url(post_id)
        warnings.append("没能读取文章链接，上面的 URL 是按博客地址拼的。")

    store.record(
        doc_id,
        post_id=post_id,
        title=title,
        url=url,
        source=ref,
        source_title=document.get("title") or title,
        categories=categories,
        tags=tags,
        content_hash=content_hash(body),
        draft=publish_flag is False,
    )
    store.save()

    if local_path:
        parent = os.path.dirname(os.path.abspath(local_path))
        if parent:
            os.makedirs(parent, exist_ok=True)
        with open(local_path, "w", encoding="utf-8", newline="\n") as fh:
            fh.write(body)
        info("已同时保存一份 Markdown 到：%s" % local_path)

    emit(100, "发布完成")
    return PublishResult(
        doc_id=doc_id, title=title, post_id=post_id, url=url,
        action=action, draft=not publish_flag, markdown=body,
        warnings=warnings,
        stats=dict(result.stats, images=len(collect_image_tokens(result.markdown))),
    )


# ---------------------------------------------------------------------------
# 本地导出（不联网发布）
# ---------------------------------------------------------------------------

def export_markdown(
    cfg: Config,
    ref: str,
    out_path: str,
    *,
    assets_dir: str | None = None,
    download_images: bool = False,
) -> dict:
    """把飞书文档抓下来存成 .md（图片可选下载到本地）。"""
    feishu, document, result = load_document(cfg, ref)
    markdown = result.markdown
    warnings = list(result.warnings)
    saved = 0

    if download_images:
        tokens = collect_image_tokens(markdown)
        if tokens:
            base = os.path.dirname(os.path.abspath(out_path))
            folder = assets_dir or os.path.join(base, "assets")
            os.makedirs(folder, exist_ok=True)
            mapping = {}
            for index, token in enumerate(tokens, 1):
                image = result.images.items.get(token)
                name = image.name if image else "image-%d.png" % index
                try:
                    data, mime = feishu.download_media(token)
                    filename = "%02d-%s" % (index, re.sub(r"[^\w.\-]+", "_", name))
                    with open(os.path.join(folder, filename), "wb") as fh:
                        fh.write(data)
                    rel = os.path.relpath(os.path.join(folder, filename), base).replace("\\", "/")
                    mapping[token] = rel
                    saved += 1
                except Exception as exc:
                    warnings.append("图片下载失败（%s）：%s" % (name, exc))
            markdown = replace_image_placeholders(markdown, mapping)

    parent = os.path.dirname(os.path.abspath(out_path))
    if parent:
        os.makedirs(parent, exist_ok=True)
    with open(out_path, "w", encoding="utf-8", newline="\n") as fh:
        fh.write(markdown)

    return {
        "doc_id": document["doc_id"],
        "title": result.title,
        "out": os.path.abspath(out_path),
        "images_saved": saved,
        "warnings": warnings,
        "stats": result.stats,
    }
