"""开发用：带假数据的网页版，用来检查界面样式（不连接飞书/博客园）。

    python tests/ui_demo.py --port 8792

然后浏览器打开 http://127.0.0.1:8792/?doc=demo
"""

from __future__ import annotations

import argparse
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from feishu2cnblogs import webapp  # noqa: E402
from feishu2cnblogs.converter import BlockConverter, collect_image_tokens, replace_image_placeholders  # noqa: E402

HERO_SVG = ("""<svg xmlns="http://www.w3.org/2000/svg" width="1200" height="520" viewBox="0 0 1200 520">
<defs>
  <linearGradient id="g" x1="0" y1="0" x2="1" y2="1">
    <stop offset="0" stop-color="#5b5bd6"/><stop offset="0.55" stop-color="#8b5cf6"/>
    <stop offset="1" stop-color="#22d3ee"/>
  </linearGradient>
  <pattern id="p" width="40" height="40" patternUnits="userSpaceOnUse">
    <path d="M40 0H0V40" fill="none" stroke="rgba(255,255,255,.14)" stroke-width="1"/>
  </pattern>
</defs>
<rect width="1200" height="520" rx="24" fill="url(#g)"/>
<rect width="1200" height="520" rx="24" fill="url(#p)"/>
<circle cx="1020" cy="110" r="150" fill="rgba(255,255,255,.10)"/>
<circle cx="180" cy="430" r="190" fill="rgba(255,255,255,.07)"/>
<text x="80" y="240" font-family="Segoe UI, sans-serif" font-size="64" font-weight="700" fill="#fff">飞书文档同步</text>
<text x="80" y="310" font-family="Segoe UI, sans-serif" font-size="28" fill="rgba(255,255,255,.82)">一份文档，一处维护，多处发布</text>
</svg>""").encode("utf-8")


def run(content="", **style):
    return {"text_run": {"content": content, "text_element_style": style}}


def text(block_id, elements):
    return {"block_id": block_id, "block_type": 2, "text": {"elements": elements}}


def heading(block_id, level, content):
    key = "heading%d" % level
    return {"block_id": block_id, "block_type": 2 + level, key: {"elements": [run(content)]}}


DEMO_DOC = {
    "doc_id": "DEMO123",
    "title": "用飞书写博客，再一键发到博客园",
    "source": "https://demo.feishu.cn/docx/DEMO123",
    "blocks": [
        {"block_id": "root", "block_type": 1, "page": {"elements": [run("用飞书写博客，再一键发到博客园")]},
         "children": ["img", "p1", "h1", "p2", "li1", "li2", "li3", "h2", "p3", "code",
                      "quote", "callout", "h3", "table", "p4", "todo"]},
        {"block_id": "img", "block_type": 24, "image": {"token": "DEMOIMG", "width": 1200, "height": 520}},
        text("p1", [run("写作和发布一直是两件事：内容在飞书里，排版和图片要重新搬一遍。这个工具把后半程自动化了——"),
                    run("粘贴链接、确认预览、点发布", bold=True), run("，剩下的交给它。")]),
        heading("h1", 1, "它做了什么"),
        text("p2", [run("读取飞书文档的块结构，翻译成博客园能渲染的 Markdown；图片下载后转到博客园图床，"),
                    run("不会出现链接过期", bold=True), run("的问题。")]),
        {"block_id": "li1", "block_type": 9, "bullet": {"elements": [run("支持 docx 和知识库 wiki 里的文档")]}},
        {"block_id": "li2", "block_type": 9, "bullet": {"elements": [run("标题、列表、代码块、表格、引用都能保留")]}},
        {"block_id": "li3", "block_type": 9, "bullet": {"elements": [run("重复发布自动更新原文章")]}},
        heading("h2", 2, "一段示例代码"),
        text("p3", [run("转换器本身也是纯标准库实现，装上就能跑：")]),
        {"block_id": "code", "block_type": 11, "code": {
            "elements": [run("from feishu2cnblogs.pipeline import publish, PublishOptions\n\n"
                             "result = publish(cfg, doc_url, PublishOptions(tags=['飞书', '工具']))\n"
                             "print(result.url)\n")],
            "style": {"language": 49}}},
        {"block_id": "quote", "block_type": 12, "quote": {"elements": [run("好的工具应该让人忘记它的存在——点一下，文章就在那里了。")]}},
        {"block_id": "callout", "block_type": 15,
         "callout": {"elements": [run("第一次使用前")], "emoji_id": "💡"},
         "children": ["callout_p"]},
        text("callout_p", [run("记得在飞书文档右上角「…」→「添加文档应用」里，把你的自建应用加进去，否则接口会返回 permission denied。")]),
        heading("h3", 3, "转换效果对照"),
        {"block_id": "table", "block_type": 28, "table": {
            "property": {"row_size": 3, "column_size": 3},
            "cells": ["c1", "c2", "c3", "c4", "c5", "c6", "c7", "c8", "c9"]}},
    ] + [
        {"block_id": "c1", "block_type": 29, "table_cell": {}, "children": ["c1t"]},
        {"block_id": "c2", "block_type": 29, "table_cell": {}, "children": ["c2t"]},
        {"block_id": "c3", "block_type": 29, "table_cell": {}, "children": ["c3t"]},
        {"block_id": "c4", "block_type": 29, "table_cell": {}, "children": ["c4t"]},
        {"block_id": "c5", "block_type": 29, "table_cell": {}, "children": ["c5t"]},
        {"block_id": "c6", "block_type": 29, "table_cell": {}, "children": ["c6t"]},
        {"block_id": "c7", "block_type": 29, "table_cell": {}, "children": ["c7t"]},
        {"block_id": "c8", "block_type": 29, "table_cell": {}, "children": ["c8t"]},
        {"block_id": "c9", "block_type": 29, "table_cell": {}, "children": ["c9t"]},
        text("c1t", [run("飞书元素")]), text("c2t", [run("博客园呈现")]), text("c3t", [run("说明")]),
        text("c4t", [run("标题 1-6")]), text("c5t", [run("h1-h6")]), text("c6t", [run("层级不变")]),
        text("c7t", [run("代码块")]), text("c8t", [run("```lang")]), text("c9t", [run("自动识别语言")]),
    ] + [
        text("p4", [run("最后，草稿和公开是两件事：")]),
        {"block_id": "todo", "block_type": 13, "todo": {
            "elements": [run("先发草稿，检查排版")], "style": {"done": True}}},
    ],
}


class DemoApp(webapp.App):
    def public_config(self):
        cfg = super().public_config()
        cfg["feishu"].update({"app_id": "cli_demo123456", "ready": True, "has_secret": True,
                              "app_secret": "abcd••••yz", "has_user_token": False})
        cfg["cnblogs"].update({"username": "demo", "blog": "demo-blog", "ready": True,
                               "has_token": True, "token": "tok••••en",
                               "categories": ["工具", "效率"], "tags": ["飞书", "自动化"]})
        return cfg

    def preview(self, ref):
        result = BlockConverter().convert(DEMO_DOC)
        markdown = replace_image_placeholders(result.markdown, {
            token: "/api/image/" + token for token in collect_image_tokens(result.markdown)
        })
        return {
            "ok": True, "doc_id": "DEMO123", "doc_title": DEMO_DOC["title"],
            "title": DEMO_DOC["title"], "markdown": result.markdown, "preview": markdown,
            "blocks": len(DEMO_DOC["blocks"]) - 9, "chars": len(result.markdown),
            "images": 1, "warnings": [], "meta": {}, "existing": None,
            "defaults": {"categories": ["工具", "效率"], "tags": ["飞书", "自动化"]},
        }

    def media(self, token):
        return HERO_SVG, "image/svg+xml"

    def history(self):
        return {"ok": True, "state_path": "demo/state.json", "items": [
            {"doc_id": "DEMO1", "post_id": "19858898", "title": "用飞书写博客，再一键发到博客园",
             "url": "https://www.cnblogs.com/demo/p/19858898", "draft": False,
             "updated_at": "2026-11-12T09:40:00+08:00", "source": "https://demo.feishu.cn/docx/DEMO1"},
            {"doc_id": "DEMO2", "post_id": "19858777", "title": "飞书文档转 Markdown 的十个坑",
             "url": "https://www.cnblogs.com/demo/p/19858777", "draft": True,
             "updated_at": "2026-11-11T21:02:00+08:00", "source": "https://demo.feishu.cn/docx/DEMO2"},
        ]}

    def check(self, doc):
        return {"ok": True,
                "feishu": {"ok": True, "auth": "tenant_access_token",
                           "document": {"title": DEMO_DOC["title"], "blocks": 42}},
                "cnblogs": {"ok": True, "blogs": ["demo-blog"],
                            "endpoint": "https://rpc.cnblogs.com/metaweblog/demo-blog"}}


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--port", type=int, default=8792)
    args = parser.parse_args()
    webapp.App = DemoApp
    demo_config = os.path.join(os.path.expanduser("~"), ".feishu2cnblogs", "demo-config.json")
    webapp.serve(port=args.port, open_browser=False, config_path=demo_config)


if __name__ == "__main__":
    main()
