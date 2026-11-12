"""配置层测试：读写、环境变量覆盖、敏感字段脱敏列表。"""

from __future__ import annotations

import os
import sys
import tempfile
import unittest
from unittest import mock

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from feishu2cnblogs.config import (  # noqa: E402
    DEFAULT_MARKDOWN_CATEGORY,
    CnblogsConfig,
    Config,
    load_config,
    save_config,
    secrets_of,
)


class TestConfig(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.path = os.path.join(self.tmp.name, "config.json")

    def tearDown(self):
        self.tmp.cleanup()

    def test_defaults_when_missing(self):
        cfg = load_config(self.path, use_env=False)
        self.assertEqual(cfg.feishu.base_url, "https://open.feishu.cn")
        self.assertFalse(cfg.feishu.ready())
        self.assertFalse(cfg.cnblogs.ready())
        self.assertEqual(cfg.cnblogs.markdown_category, DEFAULT_MARKDOWN_CATEGORY)

    def test_roundtrip(self):
        cfg = load_config(self.path, use_env=False)
        cfg.feishu.app_id = "cli_abc"
        cfg.feishu.app_secret = "secret"
        cfg.cnblogs.username = "demo"
        cfg.cnblogs.blog = "my-blog"
        cfg.cnblogs.token = "tok"
        cfg.cnblogs.categories = ["技术", "工具"]
        save_config(cfg)

        loaded = load_config(self.path, use_env=False)
        self.assertTrue(loaded.feishu.ready())
        self.assertTrue(loaded.cnblogs.ready())
        self.assertEqual(loaded.cnblogs.categories, ["技术", "工具"])
        self.assertEqual(loaded.cnblogs.api_endpoint(),
                         "https://rpc.cnblogs.com/metaweblog/my-blog")
        self.assertEqual(loaded.cnblogs.post_url("123"),
                         "https://www.cnblogs.com/my-blog/p/123")

    def test_env_overrides_file(self):
        cfg = load_config(self.path, use_env=False)
        cfg.cnblogs.username = "from-file"
        cfg.cnblogs.blog = "from-file-blog"
        save_config(cfg)
        env = {
            "CNBLOGS_USERNAME": "from-env",
            "CNBLOGS_BLOG": "env-blog",
            "CNBLOGS_TOKEN": "env-token",
            "FEISHU_APP_ID": "env-app",
            "FEISHU_APP_SECRET": "env-secret",
            "CNBLOGS_CATEGORIES": "A，B",
        }
        with mock.patch.dict(os.environ, env, clear=False):
            loaded = load_config(self.path, use_env=True)
        self.assertEqual(loaded.cnblogs.username, "from-env")
        self.assertEqual(loaded.cnblogs.blog, "env-blog")
        self.assertEqual(loaded.cnblogs.token, "env-token")
        self.assertEqual(loaded.feishu.app_id, "env-app")
        self.assertEqual(loaded.cnblogs.categories, ["A", "B"])

    def test_custom_endpoint_and_blog_url(self):
        cfg = Config(cnblogs=CnblogsConfig(
            username="u", token="t", blog="b",
            endpoint="https://example.com/metaweblog/b",
            blog_url="https://example.com/blog"))
        self.assertEqual(cfg.cnblogs.api_endpoint(), "https://example.com/metaweblog/b")
        self.assertEqual(cfg.cnblogs.post_url("9"), "https://example.com/blog/p/9")

    def test_secrets_list_includes_tokens(self):
        cfg = Config()
        cfg.feishu.app_secret = "s1"
        cfg.feishu.user_token = "u1"
        cfg.cnblogs.token = "c1"
        self.assertEqual(secrets_of(cfg), ["s1", "u1", "c1"])

    def test_state_path_relative_to_config(self):
        cfg = load_config(self.path, use_env=False)
        self.assertEqual(cfg.resolve_state_path(), os.path.join(self.tmp.name, "state.json"))

    def test_corrupt_config_raises(self):
        with open(self.path, "w", encoding="utf-8") as fh:
            fh.write("{not json")
        from feishu2cnblogs.util import UsageError
        with self.assertRaises(UsageError):
            load_config(self.path, use_env=False)


if __name__ == "__main__":
    unittest.main(verbosity=2)
