"""把测试夹具转换成 Markdown，供 render_check.js 校验预览渲染。"""

import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from feishu2cnblogs.converter import BlockConverter, replace_image_placeholders  # noqa: E402
from tests.test_converter import build_fixture  # noqa: E402

out = sys.argv[1] if len(sys.argv) > 1 else os.path.join(os.path.dirname(__file__), "preview_sample.md")

result = BlockConverter().convert(build_fixture())
markdown = replace_image_placeholders(result.markdown, {"IMGTOKEN123": "/api/image/IMGTOKEN123"})
with open(out, "w", encoding="utf-8", newline="\n") as fh:
    fh.write(markdown)
print("写入 %s（%d 字）" % (out, len(markdown)))
