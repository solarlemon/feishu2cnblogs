/* 预览渲染器测试（Node 运行）：
   node tests/render_check.js <markdown-file>
   文件内容由 tests/dump_preview.py 用真实转换器生成。 */

const fs = require('fs');
const path = require('path');
const md = require(path.join(__dirname, '..', 'feishu2cnblogs', 'web', 'markdown.js'));

let failed = 0;

function check(label, condition, extra) {
  if (condition) {
    console.log('PASS  ' + label);
  } else {
    failed++;
    console.log('FAIL  ' + label + (extra ? '  ->  ' + extra : ''));
  }
}

const file = process.argv[2] || path.join(__dirname, 'preview_sample.md');
const source = fs.readFileSync(file, 'utf8');
const html = md.renderMarkdown(source);

check('h1 渲染', /<h1>第一章 标题<\/h1>/.test(html), html.slice(0, 120));
check('h2 渲染', /<h2>1\.1 小节<\/h2>/.test(html));
check('加粗', /<strong>加粗<\/strong>/.test(html));
check('斜体', /<em>斜体<\/em>/.test(html));
check('删除线', /<del>删除线<\/del>/.test(html));
check('行内代码', /<code>行内代码<\/code>/.test(html));
check('链接', /<a href="https:\/\/example\.com\/a\?b=1"[^>]*>链接<\/a>/.test(html));
check('公式原样保留', html.indexOf('$E=mc^2$') !== -1);
check('代码块语言', /<span>python<\/span>/.test(html));
check('代码块内容', /def main\(\):/.test(html));
check('代码块复制按钮', /data-copy/.test(html));
check('无序列表', /<ul><li>一级项目/.test(html));
check('嵌套列表', /<ul><li>一级项目<ul><li>二级项目<\/li><\/ul><\/li><\/ul>/.test(html), html.match(/<ul>[\s\S]{0,160}/));
check('有序列表', /<ol><li>第一步<\/li><li>第二步<\/li><\/ol>/.test(html));
check('引用', /<blockquote>[\s\S]*被引用的话[\s\S]*<\/blockquote>/.test(html));
check('任务项已勾选', /<input type="checkbox" disabled checked>/.test(html));
check('高亮块加粗标题', /<strong>注意<\/strong>/.test(html));
check('分割线', /<hr>/.test(html));
check('表格结构', /<table><thead><tr><th>表头A<\/th><th>表头B<\/th><\/tr><\/thead>/.test(html));
check('表格单元格转义竖线', /<td>a\|b<\/td>/.test(html), html.match(/<tbody>[\s\S]*?<\/tbody>/));
check('图片走本地代理', /<img src="\/api\/image\/IMGTOKEN123"/.test(html));
check('零宽字符已清理', html.indexOf('\u200c') === -1);

// XSS：正文里的原始 HTML 必须被当成文本
const evil = md.renderMarkdown('普通文本 <script>alert(1)</script>\n\n<img src=x onerror=alert(1)>');
check('script 被转义', evil.indexOf('<script>') === -1 && evil.indexOf('&lt;script&gt;') !== -1);
check('onerror 被转义', evil.indexOf('onerror=alert(1)>') === -1);
check('危险协议链接不生效', md.renderMarkdown('[x](javascript:alert(1))').indexOf('<a ') === -1);

// 空输入
check('空输入安全', md.renderMarkdown('') === '');
check('null 安全', md.renderMarkdown(null) === '');

if (failed) {
  console.log('\n' + failed + ' 项失败');
  process.exit(1);
}
console.log('\n全部通过');
