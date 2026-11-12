/* ============================================================
   Markdown → HTML（预览用，极简实现）
   只覆盖 feishu2cnblogs 转换器产出的语法：
   标题 / 段落 / 粗斜删 / 行内代码 / 链接 / 图片 / 代码块 /
   引用 / 有序无序列表（含任务项、嵌套）/ 表格 / 分割线
   先整体转义再放行受控标签，避免 XSS。
   ============================================================ */
(function (root, factory) {
  if (typeof module === 'object' && module.exports) {
    module.exports = factory();
  } else {
    root.F2CMarkdown = factory();
  }
}(typeof self !== 'undefined' ? self : this, function () {
  'use strict';

  function esc(s) {
    return String(s == null ? '' : s).replace(/[&<>"']/g, function (c) {
      return { '&': '&amp;', '<': '&lt;', '>': '&gt;', '"': '&quot;', "'": '&#39;' }[c];
    });
  }

  function inline(text) {
    var s = esc(text);
    // 转换器输出的受控标签
    s = s.replace(/&lt;br\s*\/?&gt;/gi, '<br>')
         .replace(/&lt;(\/?)u&gt;/gi, '<$1u>');

    var codes = [];
    s = s.replace(/`([^`\n]+)`/g, function (m, code) {
      codes.push(code);
      return '\u0001' + (codes.length - 1) + '\u0001';
    });

    s = s.replace(/!\[([^\]]*)\]\(([^)\s]+)\)/g, function (m, alt, src) {
      if (!/^(https?:\/\/|\/)/i.test(src)) return m;
      return '<img src="' + src + '" alt="' + alt + '" loading="lazy">';
    });

    s = s.replace(/\[([^\]]+)\]\(([^)\s]+)\)/g, function (m, label, href) {
      if (!/^(https?:\/\/|\/|#)/i.test(href)) return m;
      return '<a href="' + href + '" target="_blank" rel="noopener noreferrer">' + label + '</a>';
    });

    s = s.replace(/\*\*([^*]+?)\*\*/g, '<strong>$1</strong>');
    s = s.replace(/(^|[^*])\*([^*\n]+?)\*(?!\*)/g, '$1<em>$2</em>');
    s = s.replace(/~~([^~]+?)~~/g, '<del>$1</del>');

    s = s.replace(/\u0001(\d+)\u0001/g, function (m, i) {
      return '<code>' + codes[+i] + '</code>';
    });
    return s;
  }

  function isBlockStart(line) {
    return /^\s*(`{3,}|~{3,})/.test(line)
      || /^#{1,6}\s+/.test(line)
      || /^\s*>/.test(line)
      || /^\s*([-*+]|\d+\.)\s+/.test(line)
      || /^\s*\|/.test(line)
      || /^\s*(?:-{3,}|\*{3,}|_{3,})\s*$/.test(line);
  }

  function codeBlock(code, lang) {
    var label = lang || 'text';
    return '<div class="code-block">'
      + '<div class="code-head"><span>' + esc(label) + '</span>'
      + '<button type="button" data-copy>复制</button></div>'
      + '<pre><code>' + esc(code) + '</code></pre></div>';
  }

  function parseList(lines, start) {
    var first = lines[start].match(/^(\s*)([-*+]|\d+\.)\s+(.*)$/);
    var baseIndent = first[1].length;
    var ordered = /^\d+\.$/.test(first[2]);
    var items = [];
    var i = start;

    while (i < lines.length) {
      var m = lines[i].match(/^(\s*)([-*+]|\d+\.)\s+(.*)$/);
      if (!m) break;
      var indent = m[1].length;
      if (indent < baseIndent) break;
      if (indent > baseIndent) {
        var sub = parseList(lines, i);
        if (items.length) items[items.length - 1] += sub.html;
        i = sub.next;
        continue;
      }
      var isOrdered = /^\d+\.$/.test(m[2]);
      if (isOrdered !== ordered) break;

      var content = m[3];
      var box = '';
      var task = content.match(/^\[( |x|X)\]\s+(.*)$/);
      if (task) {
        box = '<input type="checkbox" disabled'
          + (task[1].toLowerCase() === 'x' ? ' checked' : '') + '> ';
        content = task[2];
      }
      items.push(box + inline(content));
      i++;
    }

    var body = items.map(function (it) { return '<li>' + it + '</li>'; }).join('');
    return {
      html: (ordered ? '<ol>' : '<ul>') + body + (ordered ? '</ol>' : '</ul>'),
      next: i,
    };
  }

  function parseTable(lines, start) {
    function cells(line) {
      // 先把转义的竖线换成占位符，再按 | 切分，最后还原
      var norm = line.trim().replace(/^\|/, '').replace(/\|$/, '');
      norm = norm.replace(/\\\|/g, '\u0002');
      return norm.split('|').map(function (c) {
        return c.trim().replace(/\u0002/g, '|');
      });
    }

    var header = cells(lines[start]);
    var i = start + 2;
    var rows = [];
    while (i < lines.length && /^\s*\|/.test(lines[i])) {
      rows.push(cells(lines[i]));
      i++;
    }
    var colCount = header.length;
    function pad(arr) {
      while (arr.length < colCount) arr.push('');
      return arr.slice(0, colCount);
    }

    var html = '<table><thead><tr>'
      + pad(header).map(function (c) { return '<th>' + inline(c) + '</th>'; }).join('')
      + '</tr></thead><tbody>';
    rows.forEach(function (row) {
      html += '<tr>' + pad(row).map(function (c) { return '<td>' + inline(c) + '</td>'; }).join('') + '</tr>';
    });
    html += '</tbody></table>';
    return { html: html, next: i };
  }

  function renderMarkdown(src) {
    var lines = String(src || '')
      .replace(/\u200c/g, '')
      .replace(/\r\n?/g, '\n')
      .split('\n');
    var out = [];
    var i = 0;

    while (i < lines.length) {
      var line = lines[i];
      if (/^\s*$/.test(line)) { i++; continue; }

      var fence = line.match(/^\s*(`{3,}|~{3,})\s*([\w+#.-]*)\s*$/);
      if (fence) {
        var mark = fence[1][0];
        var len = fence[1].length;
        var lang = fence[2] || '';
        var buf = [];
        i++;
        var closer = new RegExp('^\\s*' + mark + '{' + len + ',}\\s*$');
        while (i < lines.length && !closer.test(lines[i])) {
          buf.push(lines[i]);
          i++;
        }
        i++;
        out.push(codeBlock(buf.join('\n'), lang));
        continue;
      }

      var heading = line.match(/^(#{1,6})\s+(.*?)\s*#*\s*$/);
      if (heading) {
        var level = heading[1].length;
        out.push('<h' + level + '>' + inline(heading[2]) + '</h' + level + '>');
        i++;
        continue;
      }

      if (/^\s*(?:-{3,}|\*{3,}|_{3,})\s*$/.test(line)) {
        out.push('<hr>');
        i++;
        continue;
      }

      if (/^\s*>/.test(line)) {
        var quote = [];
        while (i < lines.length && /^\s*>/.test(lines[i])) {
          quote.push(lines[i].replace(/^\s*>\s?/, ''));
          i++;
        }
        out.push('<blockquote>' + renderMarkdown(quote.join('\n')) + '</blockquote>');
        continue;
      }

      if (/^\s*\|/.test(line) && i + 1 < lines.length
          && /^\s*\|[\s:|-]+\|?\s*$/.test(lines[i + 1])) {
        var table = parseTable(lines, i);
        out.push(table.html);
        i = table.next;
        continue;
      }

      if (/^\s*([-*+]|\d+\.)\s+/.test(line)) {
        var list = parseList(lines, i);
        out.push(list.html);
        i = list.next;
        continue;
      }

      var para = [];
      while (i < lines.length && !/^\s*$/.test(lines[i]) && !isBlockStart(lines[i])) {
        para.push(lines[i]);
        i++;
      }
      out.push('<p>' + inline(para.join(' ')) + '</p>');
    }
    return out.join('\n');
  }

  return { renderMarkdown: renderMarkdown, inline: inline, escapeHtml: esc };
}));
