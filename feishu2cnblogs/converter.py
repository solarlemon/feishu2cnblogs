"""飞书 docx 块结构 → Markdown。

飞书文档的正文是一棵块树（block tree）：
    root(page) ─┬─ text
                ├─ heading1
                ├─ bullet ─── bullet   （嵌套列表）
                ├─ table ──── table_cell ─── text
                └─ image

每个「文本类」块形如 {"block_type": 2, "text": {"elements": [...], "style": {...}}}，
elements 里可能是 text_run / mention_user / mention_doc / equation / reminder / file。

本模块把它们翻译成博客园能直接渲染的 Markdown，并保证：
  · 中文紧挨 **加粗** 时不会被 Markdown 解析器吞掉（用零宽字符兜底）
  · 图片先写成占位符，由发布流程统一下载并上传到博客园图床
  · 不认识的块不丢内容：降级成链接或注释，同时给出警告
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field

# 图片占位符：<feishu-img://{token}/{name}>，发布时替换成博客园图床地址
IMG_SCHEME = "feishu-img"

# 飞书代码块 language 枚举 → Markdown 语言标识
CODE_LANGS = {
    1: "text", 2: "abap", 3: "ada", 4: "apache", 5: "apex", 6: "asm",
    7: "bash", 8: "csharp", 9: "cpp", 10: "c", 11: "cobol", 12: "css",
    13: "coffeescript", 14: "d", 15: "dart", 16: "delphi", 17: "django",
    18: "dockerfile", 19: "erlang", 20: "fortran", 21: "foxpro", 22: "go",
    23: "groovy", 24: "html", 25: "htmlbars", 26: "http", 27: "haskell",
    28: "json", 29: "java", 30: "javascript", 31: "julia", 32: "kotlin",
    33: "latex", 34: "lisp", 35: "logo", 36: "lua", 37: "matlab",
    38: "makefile", 39: "markdown", 40: "nginx", 41: "objectivec", 42: "abl",
    43: "php", 44: "perl", 45: "postscript", 46: "powershell", 47: "prolog",
    48: "protobuf", 49: "python", 50: "r", 51: "rpg", 52: "ruby", 53: "rust",
    54: "sas", 55: "scss", 56: "sql", 57: "scala", 58: "scheme", 59: "scratch",
    60: "shell", 61: "swift", 62: "thrift", 63: "typescript", 64: "vbscript",
    65: "visualbasic", 66: "xml", 67: "yaml", 68: "cmake", 69: "diff",
    70: "gherkin", 71: "graphql", 72: "glsl", 73: "properties", 74: "solidity",
    75: "toml",
}

# 块类型 → 内部节点键名
BLOCK_KEYS = {
    1: "page", 2: "text", 3: "heading1", 4: "heading2", 5: "heading3",
    6: "heading4", 7: "heading5", 8: "heading6", 9: "bullet", 10: "ordered",
    11: "code", 12: "quote", 13: "todo", 14: "bitable", 15: "callout",
    17: "chat_card", 18: "diagram", 19: "divider", 20: "file", 21: "grid",
    22: "grid_column", 23: "iframe", 24: "image", 25: "isv", 26: "mindnote",
    27: "sheet", 28: "table", 29: "table_cell", 30: "view", 31: "quote_container",
    32: "task", 33: "okr", 34: "okr_objective", 35: "okr_key_result",
    36: "okr_progress", 37: "board", 38: "text", 39: "wiki_catalog",
    40: "chat_announcement", 41: "source_synced", 42: "sub_page_list",
    43: "wiki_catalog_v2", 44: "chat_card",
}

CONTAINER_TYPES = {1, 15, 21, 22, 28, 29, 31, 34, 35}
MEDIA_TYPES = {18, 20, 23, 24, 26, 27, 32, 33, 37, 38}

ZWNJ = "\u200c"
_WS = re.compile(r"\s")


# ---------------------------------------------------------------------------
# 图片登记
# ---------------------------------------------------------------------------

@dataclass
class ImageRef:
    token: str
    name: str
    block_id: str = ""
    width: int = 0
    height: int = 0


@dataclass
class ImageRegistry:
    items: dict = field(default_factory=dict)

    def add(self, image: ImageRef) -> str:
        self.items[image.token] = image
        name = re.sub(r"[^A-Za-z0-9._/-]+", "_", image.name or "image.png")
        return "<%s://%s/%s>" % (IMG_SCHEME, image.token, name.lstrip("/") or "image.png")


def replace_image_placeholders(markdown: str, mapping: dict) -> str:
    """把占位符换成真实 URL；mapping 里没有的保留原样。"""

    def _sub(match):
        token = match.group(2)          # group(1) 是 alt 文本
        url = mapping.get(token)
        return "![](%s)" % url if url else match.group(0)

    pattern = re.compile(
        r"!\[([^\]]*)\]\((?:<)?%s://([^/>\n]+)/[^>\n)]*(?:>)?\)" % re.escape(IMG_SCHEME)
    )
    return pattern.sub(_sub, markdown)


def collect_image_tokens(markdown: str) -> list:
    pattern = re.compile(r"<%s://([^/>]+)/" % re.escape(IMG_SCHEME))
    seen = []
    for match in pattern.finditer(markdown):
        token = match.group(1)
        if token not in seen:
            seen.append(token)
    return seen


# ---------------------------------------------------------------------------
# 结果
# ---------------------------------------------------------------------------

@dataclass
class ConversionResult:
    title: str
    markdown: str
    images: ImageRegistry
    warnings: list
    stats: dict


# ---------------------------------------------------------------------------
# 转换器
# ---------------------------------------------------------------------------

def apply_style(text: str, style: dict) -> str:
    """按 text_element_style 套行内样式，顺序：代码 > 粗 > 斜 > 删除线 > 下划线。"""
    if not text:
        return text
    if not isinstance(style, dict):
        style = {}
    if style.get("inline_code"):
        ticks = "`"
        while ticks in text:
            ticks += "`"
        pad = " " if text.startswith("`") or text.endswith("`") else ""
        text = "%s%s%s%s%s" % (ticks, pad, text, pad, ticks)
    if style.get("bold"):
        text = _wrap(text, "**")
    if style.get("italic"):
        text = _wrap(text, "*")
    if style.get("strikethrough"):
        text = _wrap(text, "~~")
    if style.get("underline"):
        text = "<u>%s</u>" % text
    link = style.get("link") or {}
    url = (link or {}).get("url") if isinstance(link, dict) else ""
    if url:
        target = url
        if any(ch in url for ch in " ()<>"):
            target = "<%s>" % url
        text = "[%s](%s)" % (text, target)
    return text


def _wrap(text: str, marker: str) -> str:
    """两侧有空白时把标记往外挪一个空格，避免 ** 和空格相邻失效。"""
    if not text:
        return text
    if text[0].isspace():
        return " " + marker + text[1:] + marker
    if text[-1].isspace():
        return marker + text[:-1] + marker + " "
    return marker + text + marker


def render_elements(elements) -> str:
    """渲染一行（一个文本块）里的所有行内元素。"""
    parts = []
    for element in elements or []:
        if not isinstance(element, dict):
            continue
        style = {}
        text = ""

        run = element.get("text_run")
        if isinstance(run, dict):
            text = run.get("content") or ""
            style = run.get("text_element_style") or {}
        elif isinstance(element.get("mention_user"), dict):
            node = element["mention_user"]
            # 飞书不给名字，只有 open_id，展示成「@某人」加可辨识的 ID
            text = "@某人(%s)" % (node.get("user_id") or "unknown")
            style = node.get("text_element_style") or {}
        elif isinstance(element.get("mention_doc"), dict):
            node = element["mention_doc"]
            title = node.get("title") or "文档"
            url = node.get("url") or ""
            text = "[%s](%s)" % (title, url) if url else title
            style = node.get("text_element_style") or {}
        elif isinstance(element.get("equation"), dict):
            node = element["equation"]
            content = (node.get("content") or "").strip()
            if content:
                text = "$%s$" % content
            style = node.get("text_element_style") or {}
        elif isinstance(element.get("reminder"), dict):
            node = element["reminder"]
            text = "⏰" + (node.get("notify_time") or "")
            style = node.get("text_element_style") or {}
        elif isinstance(element.get("file"), dict):
            node = element["file"]
            token = node.get("file_token") or ""
            text = "[附件](https://feishu.cn/file/%s)" % token if token else "[附件]"
            style = node.get("text_element_style") or {}
        else:
            continue

        if text:
            parts.append(apply_style(text, style))
    return "".join(parts)


def _plain(elements) -> str:
    """取纯文本（表格单元格、标题兜底用）。"""
    out = []
    for element in elements or []:
        if not isinstance(element, dict):
            continue
        run = element.get("text_run") or {}
        if run.get("content"):
            out.append(run["content"])
        elif element.get("mention_doc"):
            out.append((element["mention_doc"].get("title") or ""))
        elif element.get("equation"):
            out.append("$%s$" % (element["equation"].get("content") or ""))
    return "".join(out)


class Context:
    """渲染上下文：有序列表计数按父块隔离，跨兄弟节点递增。"""

    def __init__(self, *, ordered_counters=None):
        self.ordered_counters = ordered_counters if ordered_counters is not None else {}


class BlockConverter:
    def __init__(self, *, inline_only: bool = False):
        self.inline_only = inline_only
        self.images = ImageRegistry()
        self.warnings = []
        self._counters = {}          # container_id → ordered list 计数
        self._block_index = {}       # block_id → block

    # ------------------------------------------------------------------
    def convert(self, document: dict) -> ConversionResult:
        blocks = document.get("blocks") or []
        self._block_index = {b.get("block_id"): b for b in blocks if b.get("block_id")}
        root = None
        # 根块就是 document 里没有 parent_id 的那个 page
        for block in blocks:
            if block.get("block_type") == 1 and not block.get("parent_id"):
                root = block
                break
        if root is None:
            root = next((b for b in blocks if b.get("block_type") == 1), None)
        if root is None:
            # 没有 page 块时把没有父块的块当作根
            top = [b for b in blocks if not b.get("parent_id") or b.get("parent_id") not in self._block_index]
            lines = []
            for block in top:
                lines.extend(self.render_block(block, depth=0, ctx=Context()))
            markdown = self._join(lines)
            return ConversionResult(
                title=document.get("title") or "",
                markdown=markdown, images=self.images,
                warnings=self.warnings, stats=self._stats(markdown, blocks),
            )

        lines = self.render_children(root, depth=0, ctx=Context())
        markdown = self._join(lines)

        title = (document.get("title") or "").strip()
        page_elements = (root.get("page") or {}).get("elements") or []
        page_text = render_elements(page_elements).strip()
        page_plain = _plain(page_elements).strip()
        if not title:
            title = page_plain or page_text
        # page 块的文字通常就是文档标题，正文里不要再重复一次
        for candidate in (page_plain, page_text):
            if candidate and markdown.startswith(candidate):
                markdown = markdown[len(candidate):].lstrip("\n")
                break
        if not title:
            title = "未命名文档"
        return ConversionResult(
            title=title,
            markdown=markdown,
            images=self.images,
            warnings=self.warnings,
            stats=self._stats(markdown, blocks),
        )

    @staticmethod
    def _stats(markdown: str, blocks: list) -> dict:
        return {
            "blocks": len(blocks),
            "images": len(re.findall(r"<%s://" % IMG_SCHEME, markdown)),
            "chars": len(markdown),
        }

    @staticmethod
    def _join(lines) -> str:
        """合并行：最多保留一个空行；列表类型切换时补一个空行，否则会被合并成同一个列表。"""
        out = []
        blank = False
        prev_list = ""
        for line in lines:
            if line is None:
                continue
            if line == "":
                if out and not blank:
                    out.append("")
                    blank = True
                continue
            stripped = line.lstrip(" ")
            kind = ""
            if not stripped.startswith(" "):
                if stripped.startswith(("- ", "* ", "+ ")):
                    kind = "bullet"
                elif re.match(r"^\d+\.\s", stripped):
                    kind = "ordered"
            if kind and prev_list and prev_list != kind and out and out[-1] != "":
                out.append("")
            prev_list = kind
            out.append(line)
            blank = False
        while out and out[-1] == "":
            out.pop()
        return "\n".join(out).strip("\n") + "\n"

    # ------------------------------------------------------------------
    def render_children(self, parent: dict, *, depth: int, ctx: Context) -> list:
        lines = []
        counters = {}
        for child_id in parent.get("children") or []:
            block = self._block_index.get(child_id)
            if block is None:
                continue
            lines.extend(self.render_block(block, depth=depth, ctx=Context(
                ordered_counters=counters)))
        return lines

    # ------------------------------------------------------------------
    def _node(self, block: dict, key: str) -> dict:
        node = block.get(key)
        return node if isinstance(node, dict) else {}

    def _elements(self, block: dict, key: str):
        return self._node(block, key).get("elements") or []

    def render_block(self, block: dict, *, depth: int, ctx: Context) -> list:
        block_type = block.get("block_type")
        key = BLOCK_KEYS.get(block_type, "")

        # ---------------- 标题 ----------------
        if block_type in (3, 4, 5, 6, 7, 8):
            level = block_type - 2          # 3→1, 4→2 ...
            level = min(level, 6)
            text = render_elements(self._elements(block, key)).strip()
            if not text:
                return []
            return ["", "%s %s" % ("#" * level, text), ""]

        # ---------------- 正文 ----------------
        if block_type in (2, 38):
            text = render_elements(self._elements(block, key))
            if not text.strip():
                return []
            return ["", text.strip("\n"), ""]

        # ---------------- 无序列表 ----------------
        if block_type == 9:
            text = render_elements(self._elements(block, key)).strip()
            head = "  " * depth + "- " + (text or "")
            lines = [head]
            lines.extend(self.render_children(block, depth=depth + 1, ctx=ctx))
            return lines

        # ---------------- 有序列表 ----------------
        if block_type == 10:
            counter_key = block.get("parent_id") or "root"
            number = ctx.ordered_counters.get(counter_key, 0) + 1
            ctx.ordered_counters[counter_key] = number
            text = render_elements(self._elements(block, key)).strip()
            head = "  " * depth + "%d. " % number + (text or "")
            lines = [head]
            lines.extend(self.render_children(block, depth=depth + 1, ctx=ctx))
            return lines

        # ---------------- 待办 ----------------
        if block_type == 13:
            node = self._node(block, "todo")
            done = bool((node.get("style") or {}).get("done"))
            text = render_elements(node.get("elements") or []).strip()
            box = "[x]" if done else "[ ]"
            lines = ["  " * depth + "- %s %s" % (box, text)]
            lines.extend(self.render_children(block, depth=depth + 1, ctx=ctx))
            return lines

        # ---------------- 代码 ----------------
        if block_type == 11:
            node = self._node(block, "code")
            lang_id = (node.get("style") or {}).get("language") or 1
            lang = CODE_LANGS.get(lang_id, "text") if isinstance(lang_id, int) else "text"
            code = _plain(node.get("elements") or []).rstrip("\n")
            if not code.strip():
                return []
            fence = "```"
            while fence in code:
                fence += "`"
            return ["", "%s%s" % (fence, "" if lang == "text" else lang), code, fence, ""]

        # ---------------- 引用 ----------------
        if block_type == 12:
            text = render_elements(self._elements(block, "quote")).strip()
            lines = []
            if text:
                lines = ["> " + line if line else ">" for line in text.split("\n")]
            inner = self.render_children(block, depth=0, ctx=ctx)
            for line in inner:
                lines.append("> " + line if line else ">")
            return ([""] + lines + [""]) if lines else []

        # ---------------- 引用容器 ----------------
        if block_type == 31:
            lines = []
            for child in self._children(block):
                for line in self.render_block(child, depth=0, ctx=ctx):
                    lines.append("> " + line if line else ">")
            return ([""] + lines + [""]) if lines else []

        # ---------------- 高亮块（callout） ----------------
        if block_type == 15:
            node = self._node(block, "callout")
            emoji = (node.get("emoji_id") or "").strip()
            title = render_elements(node.get("elements") or []).strip()
            inner = self.render_children(block, depth=0, ctx=ctx)
            # 去掉子块带来的首尾空行，避免渲染出连续的 "> >"
            while inner and inner[0] == "":
                inner.pop(0)
            while inner and inner[-1] == "":
                inner.pop()
            body = ("**%s**" % title if title else "")
            if emoji and body:
                body = emoji + " " + body
            elif emoji:
                body = emoji
            lines = ([body, ""] if body and inner else [body]) if body else []
            lines.extend(inner)
            if not lines:
                return []
            return [""] + ["> " + line if line else ">" for line in lines] + [""]

        # ---------------- 分割线 ----------------
        if block_type == 19:
            return ["", "---", ""]

        # ---------------- 图片 ----------------
        if block_type == 24:
            node = self._node(block, "image")
            token = node.get("token") or ""
            if not token:
                return []
            name = self._image_name(block, token)
            ref = ImageRef(
                token=token, name=name, block_id=block.get("block_id") or "",
                width=int(node.get("width") or 0), height=int(node.get("height") or 0),
            )
            placeholder = self.images.add(ref)
            return ["", "![%s](%s)" % (name, placeholder), ""]

        # ---------------- 文件 ----------------
        if block_type == 20:
            node = self._node(block, "file")
            token = node.get("token") or ""
            name = node.get("name") or "附件"
            if not token:
                return []
            return ["", "[📎 %s](https://feishu.cn/file/%s)" % (name, token), ""]

        # ---------------- 视频 / 附件类 ----------------
        if block_type in (23, 26, 27, 18, 32, 33, 37):
            return self._render_media(block, block_type)

        # ---------------- 表格 ----------------
        if block_type == 28:
            return self._render_table(block)

        # ---------------- 分栏 ----------------
        if block_type == 21:
            lines = []
            for column in self._children(block):
                lines.extend(self.render_block(column, depth=depth, ctx=ctx))
            return lines

        if block_type == 22:
            return self.render_children(block, depth=depth, ctx=ctx)

        # ---------------- 表格单元格（单独出现时） ----------------
        if block_type == 29:
            return self.render_children(block, depth=0, ctx=ctx)

        # ---------------- 页面 / 子页面 ----------------
        if block_type == 1:
            return self.render_children(block, depth=depth, ctx=ctx)

        if block_type == 42:
            node = self._node(block, "sub_page_list")
            lines = []
            for item in node.get("sub_page_list_items") or []:
                title = item.get("title") or "子页面"
                url = item.get("url") or ""
                lines.append("- [%s](%s)" % (title, url) if url else "- %s" % title)
            return (["", "**相关页面**", ""] + lines + [""]) if lines else []

        # ---------------- 其他容器 ----------------
        if block_type in CONTAINER_TYPES and block.get("children"):
            return self.render_children(block, depth=depth, ctx=ctx)

        # ---------------- 兜底 ----------------
        return self._render_unknown(block)

    # ------------------------------------------------------------------
    def _children(self, block: dict) -> list:
        out = []
        for child_id in block.get("children") or []:
            child = self._block_index.get(child_id)
            if child is not None:
                out.append(child)
        return out

    def _image_name(self, block: dict, token: str) -> str:
        node = self._node(block, "image")
        for key in ("name", "file_name", "title"):
            if node.get(key):
                return str(node[key])
        return "image-%s.png" % token[:8]

    def _render_media(self, block: dict, block_type: int) -> list:
        key = BLOCK_KEYS.get(block_type, "")
        node = self._node(block, key)
        labels = {
            23: "内嵌网页 iframe",
            26: "思维笔记",
            27: "电子表格",
            18: "流程图/画板",
            32: "任务",
            33: "OKR",
            37: "画板",
        }
        label = labels.get(block_type, "媒体")
        token = node.get("token") or node.get("file_token") or ""
        url = node.get("url") or ""
        if block_type in (23, 26, 27) and not url:
            url = "https://feishu.cn/%s/%s" % ("mindnotes" if block_type == 26 else "sheets", token)
        if url:
            text = "[%s](%s)" % (label, url)
        elif token:
            text = "[%s](https://feishu.cn/file/%s)" % (label, token)
        else:
            text = ""
        if not text:
            self.warnings.append("跳过了不支持的块：%s（block_type=%s）" % (label, block_type))
            return []
        self.warnings.append(
            "「%s」无法在博客园里原样渲染，已降级为链接，建议在发布前手动检查。" % label
        )
        return ["", "> " + text, ""]

    def _render_table(self, block: dict) -> list:
        node = self._node(block, "table")
        prop = node.get("property") or {}
        rows = int(prop.get("row_size") or 0)
        cols = int(prop.get("column_size") or 0)
        cells = [self._block_index.get(cid) for cid in (node.get("cells") or [])]
        if rows <= 0 or cols <= 0 or not cells:
            return self._render_unknown(block)

        grid = []
        for r in range(rows):
            row = []
            for c in range(cols):
                index = r * cols + c
                cell = cells[index] if index < len(cells) else None
                row.append(self._cell_text(cell))
            grid.append(row)

        # 第一行带表头；如果全是空单元格就退化成普通行
        header = grid[0]
        body = grid[1:]
        lines = ["", "| " + " | ".join(header) + " |",
                 "| " + " | ".join("---" for _ in header) + " |"]
        for row in body:
            lines.append("| " + " | ".join(row) + " |")
        lines.append("")
        for cell in cells:
            if not isinstance(cell, dict):
                continue
            size = (self._node(cell, "table_cell").get("property") or {})
            if (size.get("row_span") or 1) > 1 or (size.get("col_span") or 1) > 1:
                self.warnings.append("表格里有合并单元格，Markdown 无法表达，已按普通单元格展开。")
                break
        return lines

    def _cell_text(self, cell) -> str:
        if not isinstance(cell, dict):
            return ""
        texts = []
        for child in self._children(cell):
            block_type = child.get("block_type")
            key = BLOCK_KEYS.get(block_type, "")
            if block_type in (2, 38, 3, 4, 5, 6, 7, 8, 9, 10, 12, 13):
                text = render_elements(self._elements(child, key)).strip()
                if text:
                    texts.append(text)
            elif block_type == 11:
                code = _plain(self._node(child, "code").get("elements") or []).strip()
                if code:
                    texts.append("`%s`" % code.replace("\n", " "))
            elif block_type == 24:
                token = self._node(child, "image").get("token") or ""
                if token:
                    placeholder = self.images.add(ImageRef(
                        token=token, name=self._image_name(child, token),
                        block_id=child.get("block_id") or "",
                    ))
                    texts.append("![%s](%s)" % ("图片", placeholder))
            elif child.get("children"):
                text = self._cell_text(child)
                if text:
                    texts.append(text)
        text = "<br>".join(texts)
        return text.replace("|", "\\|").replace("\n", "<br>")

    def _render_unknown(self, block: dict) -> list:
        block_type = block.get("block_type")
        key = BLOCK_KEYS.get(block_type, "")
        text = ""
        if key:
            text = render_elements(self._elements(block, key)).strip()
        if text:
            return ["", text, ""]
        if block.get("children"):
            return self.render_children(block, depth=0, ctx=Context())
        self.warnings.append("跳过了未支持的块 block_type=%s" % block_type)
        return []


# ---------------------------------------------------------------------------
# 摘要 / 标题工具
# ---------------------------------------------------------------------------

def make_excerpt(markdown: str, limit: int = 160) -> str:
    """从正文里抠一段纯文本当摘要。"""
    text = re.sub(r"```.*?```", " ", markdown or "", flags=re.S)
    text = re.sub(r"!\[[^\]]*\]\([^)]*\)", " ", text)
    text = re.sub(r"\[([^\]]*)\]\([^)]*\)", r"\1", text)
    text = re.sub(r"<[^>]+>", " ", text)
    text = re.sub(r"[#>*_`~\-]{1,}", " ", text)
    text = re.sub(r"\s+", " ", text).strip()
    if len(text) <= limit:
        return text
    cut = text[:limit]
    for sep in ("。", "！", "？", ".", "；", ";", "，", ","):
        index = cut.rfind(sep)
        if index > limit // 2:
            return cut[: index + 1]
    return cut + "…"
