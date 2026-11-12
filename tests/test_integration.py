"""端到端测试：用假的飞书 / 博客园客户端跑完整的发布链路。

覆盖：新建 → 图片上传替换 → 状态落盘 → 重复发布改成更新 → 草稿/公开开关。
"""

from __future__ import annotations

import os
import sys
import tempfile
import unittest
from unittest import mock

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from feishu2cnblogs.config import CnblogsConfig, Config, FeishuConfig  # noqa: E402
from feishu2cnblogs.pipeline import PublishOptions, publish  # noqa: E402

# 最小可用文档：标题 + 一段正文 + 一张图
DOCUMENT = {
    "doc_id": "doccn123",
    "title": "端到端测试",
    "source": "https://x.feishu.cn/docx/doccn123",
    "blocks": [
        {"block_id": "root", "block_type": 1, "page": {"elements": [
            {"text_run": {"content": "端到端测试"}}]}, "children": ["p1", "img1"]},
        {"block_id": "p1", "block_type": 2, "parent_id": "root",
         "text": {"elements": [{"text_run": {"content": "正文 "}},
                               {"text_run": {"content": "加粗", "text_element_style": {"bold": True}}}]}},
        {"block_id": "img1", "block_type": 24, "parent_id": "root",
         "image": {"token": "IMG_TOKEN_1", "width": 10, "height": 10}},
    ],
}


class FakeFeishu:
    def __init__(self, cfg):
        self.cfg = cfg
        self.downloaded = []

    def load_document(self, ref):
        self.ref = ref
        return DOCUMENT

    def download_media(self, token):
        self.downloaded.append(token)
        return b"\x89PNG\r\n\x1a\nfake", "image/png"


class FakeBlog:
    posts = {}
    uploads = []
    next_id = [100]

    def __init__(self, cfg):
        self.cfg = cfg

    def upload_media(self, data, name, mime=None):
        FakeBlog.uploads.append((name, mime, len(data)))
        return "https://img2024.cnblogs.com/blog/1/%s" % name

    def new_post(self, post, publish=True):
        post_id = str(FakeBlog.next_id[0])
        FakeBlog.next_id[0] += 1
        FakeBlog.posts[post_id] = dict(post)
        FakeBlog.posts[post_id]["_published"] = publish
        return post_id

    def edit_post(self, post_id, post, publish=True):
        current = FakeBlog.posts.get(post_id)
        if current is None:
            raise AssertionError("edit_post 被调用但文章不存在：%s" % post_id)
        merged = dict(current)
        merged.update(post)
        merged["_published"] = publish
        FakeBlog.posts[post_id] = merged
        return True

    def get_post(self, post_id):
        return dict(FakeBlog.posts[post_id], link="https://www.cnblogs.com/demo/p/%s" % post_id)

    def post_url(self, post_id, post=None):
        return "https://www.cnblogs.com/demo/p/%s" % post_id


def make_config(tmpdir):
    cfg = Config(
        feishu=FeishuConfig(app_id="cli_x", app_secret="secret_x"),
        cnblogs=CnblogsConfig(username="demo", token="tok", blog="demo"),
    )
    cfg.path = os.path.join(tmpdir, "config.json")
    return cfg


class TestPublishPipeline(unittest.TestCase):
    def setUp(self):
        FakeBlog.posts.clear()
        FakeBlog.uploads.clear()
        FakeBlog.next_id = [100]
        self.tmp = tempfile.TemporaryDirectory()
        self.cfg = make_config(self.tmp.name)
        self.patchers = [
            mock.patch("feishu2cnblogs.pipeline.FeishuClient", FakeFeishu),
            mock.patch("feishu2cnblogs.pipeline.CnblogsClient", FakeBlog),
        ]
        for patcher in self.patchers:
            patcher.start()

    def tearDown(self):
        for patcher in self.patchers:
            patcher.stop()
        self.tmp.cleanup()

    def test_creates_draft_and_uploads_image(self):
        result = publish(self.cfg, "https://x.feishu.cn/docx/doccn123",
                         PublishOptions(categories=["工具"], tags=["飞书"]))
        self.assertEqual(result.action, "created")
        self.assertTrue(result.draft)
        self.assertEqual(result.post_id, "100")
        self.assertTrue(FakeBlog.uploads[0][0].endswith(".png"))
        body = FakeBlog.posts["100"]["description"]
        self.assertIn("https://img2024.cnblogs.com/blog/1/", body)
        self.assertNotIn("feishu-img", body)
        self.assertIn("[Markdown]", FakeBlog.posts["100"]["categories"])
        self.assertIn("工具", FakeBlog.posts["100"]["categories"])
        self.assertEqual(FakeBlog.posts["100"]["mt_keywords"], "飞书")
        self.assertFalse(FakeBlog.posts["100"]["_published"])

    def test_state_recorded(self):
        publish(self.cfg, "https://x.feishu.cn/docx/doccn123", PublishOptions())
        state = os.path.join(self.tmp.name, "state.json")
        self.assertTrue(os.path.exists(state))
        with open(state, encoding="utf-8") as fh:
            text = fh.read()
        self.assertIn("doccn123", text)
        self.assertNotIn("tok", text)          # 令牌不落状态文件

    def test_second_publish_updates_same_post(self):
        first = publish(self.cfg, "https://x.feishu.cn/docx/doccn123", PublishOptions())
        second = publish(self.cfg, "https://x.feishu.cn/docx/doccn123", PublishOptions(publish=True))
        self.assertEqual(first.post_id, second.post_id)
        self.assertEqual(second.action, "updated")
        self.assertEqual(len(FakeBlog.posts), 1)
        self.assertTrue(FakeBlog.posts[first.post_id]["_published"])

    def test_force_new_creates_another_post(self):
        first = publish(self.cfg, "https://x.feishu.cn/docx/doccn123", PublishOptions())
        second = publish(self.cfg, "https://x.feishu.cn/docx/doccn123",
                         PublishOptions(force_new=True))
        self.assertNotEqual(first.post_id, second.post_id)
        self.assertEqual(len(FakeBlog.posts), 2)

    def test_title_override_and_source_link(self):
        result = publish(self.cfg, "https://x.feishu.cn/docx/doccn123",
                         PublishOptions(title="自定义标题", source_link=True))
        self.assertEqual(result.title, "自定义标题")
        self.assertIn("原文：", FakeBlog.posts[result.post_id]["description"])

    def test_ai_declaration_and_excerpt(self):
        result = publish(self.cfg, "https://x.feishu.cn/docx/doccn123",
                         PublishOptions(ai_declaration=True))
        post = FakeBlog.posts[result.post_id]
        self.assertIn("AI 辅助整理", post["description"])
        self.assertTrue(post.get("mt_excerpt"))
        self.assertLessEqual(len(post["mt_excerpt"]), 161)

    def test_save_md(self):
        out = os.path.join(self.tmp.name, "out", "post.md")
        publish(self.cfg, "https://x.feishu.cn/docx/doccn123",
                PublishOptions(), local_path=out)
        self.assertTrue(os.path.exists(out))
        with open(out, encoding="utf-8") as fh:
            self.assertIn("加粗", fh.read())

    def test_meta_block_overrides_tags(self):
        doc = dict(DOCUMENT)
        doc = {**DOCUMENT}
        doc["blocks"] = [
            {"block_id": "root", "block_type": 1, "page": {"elements": [
                {"text_run": {"content": "端到端测试"}}]}, "children": ["meta", "p1"]},
            {"block_id": "meta", "block_type": 2, "parent_id": "root",
             "text": {"elements": [{"text_run": {
                 "content": "<!--\ntags: 标签A, 标签B\ncategories: 分类X\n-->"}}]}},
            {"block_id": "p1", "block_type": 2, "parent_id": "root",
             "text": {"elements": [{"text_run": {"content": "正文"}}]}},
        ]
        with mock.patch.object(FakeFeishu, "load_document", lambda self, ref: doc):
            result = publish(self.cfg, "doc", PublishOptions())
        post = FakeBlog.posts[result.post_id]
        self.assertEqual(post["mt_keywords"], "标签A,标签B")
        self.assertIn("分类X", post["categories"])
        self.assertNotIn("<!--", post["description"])


class TestPublishErrors(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.cfg = make_config(self.tmp.name)

    def tearDown(self):
        self.tmp.cleanup()

    def test_missing_cnblogs_credentials(self):
        cfg = make_config(self.tmp.name)
        cfg.cnblogs = CnblogsConfig()
        with mock.patch("feishu2cnblogs.pipeline.FeishuClient", FakeFeishu), \
                mock.patch("feishu2cnblogs.pipeline.CnblogsClient", FakeBlog):
            from feishu2cnblogs.util import AppError
            with self.assertRaises(AppError):
                publish(cfg, "doc", PublishOptions())


if __name__ == "__main__":
    unittest.main(verbosity=2)
