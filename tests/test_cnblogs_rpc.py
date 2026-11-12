"""博客园 XML-RPC 协议层测试：起一个本地 XML-RPC 服务，验证请求/响应真实序列化。

不需要真实博客园账号，验证的是：
  · 端点拼接、方法名、参数顺序
  · newPost 返回 postid 的解析（含带引号/bytes 的情况）
  · newMediaObject 的 Binary 上传
  · editPost 先 getPost 再整体替换（不会把原字段冲掉）
"""

from __future__ import annotations

import os
import sys
import threading
import unittest
import xmlrpc.client
from xmlrpc.server import SimpleXMLRPCServer

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from feishu2cnblogs.blog import CnblogsClient, _extract_post_id  # noqa: E402
from feishu2cnblogs.config import CnblogsConfig, Config, FeishuConfig  # noqa: E402


class FakeCnblogs:
    def __init__(self):
        self.calls = []
        self.posts = {
            "501": {
                "postid": "501",
                "title": "旧标题",
                "description": "旧内容",
                "categories": ["[Markdown]", "技术"],
                "mt_keywords": "旧标签",
                "link": "https://www.cnblogs.com/demo/p/501",
            }
        }

    # ---- blogger ----
    def getUsersBlogs(self, appkey, username, password):
        self.calls.append(("getUsersBlogs", appkey, username, password))
        if password != "good-token":
            raise xmlrpc.client.Fault(3, "token invalid")
        return [{"blogid": "demo", "blogName": "demo", "url": "https://www.cnblogs.com/demo/"}]

    # ---- metaWeblog ----
    def newPost(self, blogid, username, password, post, publish):
        self.calls.append(("newPost", blogid, dict(post), publish))
        post_id = str(600 + len(self.posts))
        self.posts[post_id] = dict(post, postid=post_id)
        return post_id

    def editPost(self, postid, username, password, post, publish):
        self.calls.append(("editPost", postid, dict(post), publish))
        if postid not in self.posts:
            raise xmlrpc.client.Fault(1, "post not found")
        self.posts[postid] = dict(post, postid=postid)
        return True

    def getPost(self, postid, username, password):
        self.calls.append(("getPost", postid))
        if postid not in self.posts:
            raise xmlrpc.client.Fault(1, "post not found")
        return self.posts[postid]

    def getCategories(self, blogid, username, password):
        return [{"title": "随笔", "categoryid": "1"}, {"title": "技术", "categoryid": "2"}]

    def newMediaObject(self, blogid, username, password, media):
        self.calls.append(("newMediaObject", media["name"], media["type"], len(media["bits"].data)))
        return {"url": "https://img2024.cnblogs.com/blog/1/%s" % media["name"]}


def make_config(token="good-token"):
    return Config(
        feishu=FeishuConfig(app_id="a", app_secret="b"),
        cnblogs=CnblogsConfig(username="demo", token=token, blog="demo"),
    )


class TestCnblogsRPC(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.backend = FakeCnblogs()
        cls.server = SimpleXMLRPCServer(("127.0.0.1", 0), allow_none=True, logRequests=False)
        # 客户端调用的是 blogger.getUsersBlogs / metaWeblog.newPost 这种带命名空间的方法
        for method in ("getUsersBlogs", "newPost", "editPost", "getPost",
                       "getCategories", "newMediaObject"):
            func = getattr(cls.backend, method)
            for name in ("blogger." + method, "metaWeblog." + method, method):
                cls.server.register_function(func, name)
        cls.port = cls.server.server_address[1]
        cls.thread = threading.Thread(target=cls.server.serve_forever, daemon=True)
        cls.thread.start()

    @classmethod
    def tearDownClass(cls):
        cls.server.shutdown()
        cls.server.server_close()

    def setUp(self):
        self.backend.calls.clear()
        # 每个用例都从同一份初始数据开始，避免 postid 自增导致断言漂移
        self.backend.__init__()

    def client(self, token="good-token"):
        cfg = make_config(token)
        client = CnblogsClient(cfg)
        # 把 https 的 ServerProxy 换成指向本地假服务
        client._server = lambda: xmlrpc.client.ServerProxy(
            "http://127.0.0.1:%d/" % self.port, allow_none=False, use_builtin_types=True)
        return client

    def test_endpoint_from_blog_name(self):
        client = CnblogsClient(make_config())
        self.assertEqual(client.endpoint, "https://rpc.cnblogs.com/metaweblog/demo")

    def test_check_ok(self):
        result = self.client().check()
        self.assertEqual(result["blogs"][0]["blogName"], "demo")
        self.assertEqual(self.backend.calls[0][0], "getUsersBlogs")

    def test_check_bad_token_raises(self):
        from feishu2cnblogs.util import CnblogsError
        with self.assertRaises(CnblogsError) as ctx:
            self.client("bad-token").check()
        self.assertIn("token invalid", str(ctx.exception))

    def test_new_post_and_extract_id(self):
        client = self.client()
        post_id = client.new_post({"title": "T", "description": "D", "categories": ["[Markdown]"]},
                                  publish=True)
        self.assertEqual(post_id, "601")
        call = self.backend.calls[-1]
        self.assertEqual(call[0], "newPost")
        self.assertEqual(call[2]["title"], "T")
        self.assertTrue(call[3])

    def test_draft_flag_false(self):
        self.client().new_post({"title": "T", "description": "D"}, publish=False)
        self.assertFalse(self.backend.calls[-1][3])

    def test_upload_media_binary(self):
        client = self.client()
        url = client.upload_media(b"\x89PNGdata", "pic.png", "image/png")
        self.assertEqual(url, "https://img2024.cnblogs.com/blog/1/pic.png")
        call = self.backend.calls[-1]
        self.assertEqual(call[1], "pic.png")
        self.assertEqual(call[2], "image/png")
        self.assertEqual(call[3], 8)

    def test_edit_post_preserves_other_fields(self):
        client = self.client()
        ok = client.edit_post("501", {"description": "新内容"}, publish=True)
        self.assertTrue(ok)
        methods = [c[0] for c in self.backend.calls]
        self.assertEqual(methods, ["getPost", "editPost"])
        saved = self.backend.posts["501"]
        self.assertEqual(saved["title"], "旧标题")          # 没被冲掉
        self.assertEqual(saved["categories"], ["[Markdown]", "技术"])
        self.assertEqual(saved["description"], "新内容")
        self.assertNotIn("postid", self.backend.calls[1][2])  # postid 不作为字段回传

    def test_categories(self):
        self.assertEqual(self.client().get_categories(), ["随笔", "技术"])

    def test_post_url_prefers_link(self):
        client = self.client()
        self.assertEqual(client.post_url("501", self.backend.posts["501"]),
                         "https://www.cnblogs.com/demo/p/501")

    def test_post_url_fallback(self):
        client = self.client()
        self.assertEqual(client.post_url("999"), "https://www.cnblogs.com/demo/p/999")


class TestPostIdExtraction(unittest.TestCase):
    def test_string(self):
        self.assertEqual(_extract_post_id("12345"), "12345")

    def test_quoted(self):
        self.assertEqual(_extract_post_id('"12345"'), "12345")

    def test_bytes(self):
        self.assertEqual(_extract_post_id(b"12345"), "12345")

    def test_int(self):
        self.assertEqual(_extract_post_id(12345), "12345")


if __name__ == "__main__":
    unittest.main(verbosity=2)
