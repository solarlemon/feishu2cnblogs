"""转换器单元测试：用一份模拟的飞书块结构覆盖所有主要块类型。

运行：python -m unittest discover -s tests -v
"""

from __future__ import annotations

import os
import sys
import unittest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from feishu2cnblogs.converter import (  # noqa: E402
    BlockConverter,
    apply_style,
    collect_image_tokens,
    make_excerpt,
    replace_image_placeholders,
)


def run(text="", **style):
    return {"text_run": {"content": text, "text_element_style": style}}


def text_block(block_id, elements):
    return {"block_id": block_id, "block_type": 2, "text": {"elements": elements}}


def heading(block_id, level, content):
    return {
        "block_id": block_id,
        "block_type": 2 + level,
        {"1": "heading1", "2": "heading2", "3": "heading3"}[str(level)]: {
            "elements": [run(content)]
        },
    }


def build_fixture():
    blocks = [
        {"block_id": "root", "block_type": 1, "page": {"elements": [run("测试文档")]},
         "children": ["h1", "h2", "p1", "bullet1", "ordered1", "ordered2", "code1",
                      "quote1", "todo1", "callout1", "divider1", "img1", "table1",
                      "file1", "unknown1", "nested1"]},
        heading("h1", 1, "第一章 标题"),
        heading("h2", 2, "1.1 小节"),
        text_block("p1", [
            run("中文"), run("加粗", bold=True), run("混排，"),
            run("斜体", italic=True), run("、"),
            run("删除线", strikethrough=True), run("、"),
            run("行内代码", inline_code=True), run("，"),
            run("链接", link={"url": "https://example.com/a?b=1"}),
            run("，公式 "), {"equation": {"content": "E=mc^2"}},
            run("，@"), {"mention_user": {"user_id": "ou_123"}},
            run("，参考 "), {"mention_doc": {"title": "另一篇", "url": "https://x/docx/abc", "obj_type": 22}},
        ]),
        {"block_id": "bullet1", "block_type": 9, "bullet": {"elements": [run("一级项目")]},
         "children": ["bullet1a"]},
        {"block_id": "bullet1a", "block_type": 9, "bullet": {"elements": [run("二级项目")]},
         "children": []},
        {"block_id": "ordered1", "block_type": 10, "ordered": {"elements": [run("第一步")]},
         "children": []},
        {"block_id": "ordered2", "block_type": 10, "ordered": {"elements": [run("第二步")]},
         "children": []},
        {"block_id": "code1", "block_type": 11,
         "code": {"elements": [run("def main():\n    print('hi')\n")],
                  "style": {"language": 49, "wrap": False}}},
        {"block_id": "quote1", "block_type": 12,
         "quote": {"elements": [run("被引用的话")]}},
        {"block_id": "todo1", "block_type": 13,
         "todo": {"elements": [run("已完成事项")], "style": {"done": True}}},
        {"block_id": "callout1", "block_type": 15,
         "callout": {"elements": [run("注意")], "emoji_id": "warning"},
         "children": ["callout_text"]},
        {"block_id": "callout_text", "block_type": 2,
         "text": {"elements": [run("这里有坑")]}},
        {"block_id": "divider1", "block_type": 19, "divider": {}},
        {"block_id": "img1", "block_type": 24,
         "image": {"token": "IMGTOKEN123", "width": 800, "height": 600}},
        {"block_id": "table1", "block_type": 28,
         "table": {"property": {"row_size": 2, "column_size": 2, "header_row": True},
                   "cells": ["c11", "c12", "c21", "c22"]}},
        {"block_id": "c11", "block_type": 29, "table_cell": {}, "children": ["c11t"]},
        {"block_id": "c12", "block_type": 29, "table_cell": {}, "children": ["c12t"]},
        {"block_id": "c21", "block_type": 29, "table_cell": {}, "children": ["c21t"]},
        {"block_id": "c22", "block_type": 29, "table_cell": {}, "children": ["c22t"]},
        {"block_id": "c11t", "block_type": 2, "text": {"elements": [run("表头A")]}},
        {"block_id": "c12t", "block_type": 2, "text": {"elements": [run("表头B")]}},
        {"block_id": "c21t", "block_type": 2, "text": {"elements": [run("a|b")]}},
        {"block_id": "c22t", "block_type": 2, "text": {"elements": [run("值2")]}},
        {"block_id": "file1", "block_type": 20,
         "file": {"token": "FILETOKEN", "name": "需求.docx"}},
        {"block_id": "unknown1", "block_type": 999, "whatever": {}},
        {"block_id": "nested1", "block_type": 21, "grid": {"column_size": 2},
         "children": ["col1"]},
        {"block_id": "col1", "block_type": 22, "grid_column": {}, "children": ["col1p"]},
        {"block_id": "col1p", "block_type": 2, "text": {"elements": [run("分栏里的内容")]}},
    ]
    # 补上两个有序列表项的父节点
    blocks[7]["parent_id"] = "root"
    blocks[8]["parent_id"] = "root"
    return {
        "doc_id": "doccn123",
        "title": "测试文档",
        "blocks": blocks,
        "source": "https://x.feishu.cn/docx/doccn123",
    }


class TestConversion(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.result = BlockConverter().convert(build_fixture())
        cls.md = cls.result.markdown

    def test_title(self):
        self.assertEqual(self.result.title, "测试文档")

    def test_headings(self):
        self.assertIn("# 第一章 标题", self.md)
        self.assertIn("## 1.1 小节", self.md)

    def test_inline_styles(self):
        self.assertIn("**加粗**", self.md)
        self.assertIn("*斜体*", self.md)
        self.assertIn("~~删除线~~", self.md)
        self.assertIn("`行内代码`", self.md)
        self.assertIn("[链接](https://example.com/a?b=1)", self.md)
        self.assertIn("$E=mc^2$", self.md)
        self.assertIn("@某人(ou_123)", self.md)
        self.assertIn("[另一篇](https://x/docx/abc)", self.md)

    def test_nested_lists(self):
        self.assertIn("- 一级项目", self.md)
        self.assertIn("  - 二级项目", self.md)

    def test_ordered_list_numbering(self):
        self.assertIn("1. 第一步", self.md)
        self.assertIn("2. 第二步", self.md)

    def test_code_block(self):
        self.assertIn("```python", self.md)
        self.assertIn("def main():", self.md)

    def test_quote_and_todo(self):
        self.assertIn("> 被引用的话", self.md)
        self.assertIn("- [x] 已完成事项", self.md)

    def test_callout(self):
        self.assertIn("> warning **注意**", self.md)
        self.assertIn("> 这里有坑", self.md)
        self.assertNotIn("> >", self.md)

    def test_divider(self):
        self.assertIn("---", self.md)

    def test_image_placeholder(self):
        self.assertIn("<feishu-img://IMGTOKEN123/", self.md)
        self.assertEqual(collect_image_tokens(self.md), ["IMGTOKEN123"])

    def test_table(self):
        self.assertIn("| 表头A | 表头B |", self.md)
        self.assertIn("| --- | --- |", self.md)
        self.assertIn("a\\|b", self.md)          # 单元格里的竖线被转义
        self.assertIn("| 值2 |", self.md)

    def test_file_block_degraded_to_link(self):
        self.assertIn("需求.docx", self.md)
        self.assertIn("https://feishu.cn/file/FILETOKEN", self.md)

    def test_unknown_block_warned_not_crash(self):
        self.assertTrue(any("block_type=999" in w for w in self.result.warnings))

    def test_grid_content_kept(self):
        self.assertIn("分栏里的内容", self.md)

    def test_placeholder_replacement(self):
        out = replace_image_placeholders(
            self.md, {"IMGTOKEN123": "https://img2024.cnblogs.com/a.png"})
        self.assertIn("![](https://img2024.cnblogs.com/a.png)", out)
        self.assertNotIn("feishu-img", out)

    def test_placeholder_kept_when_upload_failed(self):
        out = replace_image_placeholders(self.md, {})
        self.assertIn("feishu-img://IMGTOKEN123", out)


class TestInlineHelpers(unittest.TestCase):
    def test_bold_next_to_chinese(self):
        self.assertIn("**加粗**", apply_style("加粗", {"bold": True}))

    def test_bold_with_leading_space(self):
        self.assertEqual(apply_style(" x", {"bold": True}), " **x**")

    def test_code_with_backticks(self):
        out = apply_style("a`b", {"inline_code": True})
        self.assertTrue(out.startswith("``"))
        self.assertTrue(out.endswith("``"))

    def test_link_with_spaces(self):
        out = apply_style("文本", {"link": {"url": "https://a.com/x y"}})
        self.assertIn("<https://a.com/x y>", out)

    def test_bold_and_link_combined(self):
        out = apply_style("点我", {"bold": True, "link": {"url": "https://a.com"}})
        self.assertEqual(out, "[**点我**](https://a.com)")


class TestExcerpt(unittest.TestCase):
    def test_excerpt_strips_markup(self):
        text = make_excerpt("# 标题\n\n**加粗**内容，还有[链接](https://a.com)和`代码`。")
        self.assertNotIn("#", text)
        self.assertNotIn("**", text)
        self.assertNotIn("https://", text)
        self.assertLessEqual(len(text), 161)


if __name__ == "__main__":
    unittest.main(verbosity=2)
