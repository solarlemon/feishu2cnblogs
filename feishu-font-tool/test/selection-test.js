(async () => {
  const sleep = (ms) => new Promise((resolve) => setTimeout(resolve, ms));
  const results = { pass: [], fail: [], info: {} };
  const assert = (name, condition, detail) => {
    if (condition) results.pass.push(name);
    else results.fail.push({ name, detail: detail == null ? '' : String(detail) });
  };

  await sleep(900);
  const host = document.getElementById('fft-ui-host');
  const sr = host && host.shadowRoot;
  assert('UI host mounted', Boolean(host), 'no #fft-ui-host');
  assert('shadow root created', Boolean(sr), 'no shadowRoot');
  if (!sr) return JSON.stringify(results);

  const panel = sr.getElementById('fft-panel');
  const fab = sr.getElementById('fft-fab');
  const font = sr.getElementById('fft-font');
  const size = sr.getElementById('fft-size');
  const applyAll = sr.getElementById('fft-apply-all');
  const applySel = sr.getElementById('fft-apply-sel');
  const clearSel = sr.getElementById('fft-clear-sel');
  const reset = sr.getElementById('fft-reset');
  const status = sr.getElementById('fft-status');

  results.info.fontOptions = font.options.length;
  results.info.sizeOptions = size.options.length;
  assert('font options populated', font.options.length >= 10, font.options.length);
  assert('size options populated', size.options.length >= 10, size.options.length);
  assert('panel starts hidden', panel.hidden, panel.hidden);

  fab.click();
  await sleep(80);
  assert('panel opens', !panel.hidden, panel.hidden);
  const panelStyle = getComputedStyle(panel);
  results.info.panel = {
    display: panelStyle.display,
    width: panelStyle.width,
    background: panelStyle.backgroundColor
  };
  assert('panel is styled', panelStyle.display === 'block' && panelStyle.width === '336px', JSON.stringify(results.info.panel));

  const setSelect = (el, value) => {
    el.value = value;
    el.dispatchEvent(new Event('change', { bubbles: true }));
  };
  const firstTextNode = (el) => {
    const walker = document.createTreeWalker(el, NodeFilter.SHOW_TEXT);
    return walker.nextNode();
  };
  const selectRange = (startNode, startOffset, endNode, endOffset) => {
    const range = document.createRange();
    range.setStart(startNode, startOffset);
    range.setEnd(endNode, endOffset);
    const selection = window.getSelection();
    selection.removeAllRanges();
    selection.addRange(range);
    document.dispatchEvent(new Event('selectionchange', { bubbles: true }));
  };
  const norm = (value) => String(value).replace(/\s+/g, ' ').trim();

  const p1 = document.getElementById('p1');
  const p2 = document.getElementById('p2');
  const p3 = document.getElementById('p3');
  const h2 = document.getElementById('h2');
  const title = document.querySelector('.page-block-content .ace-line');
  const code = document.getElementById('code');

  const beforeAll = norm(document.querySelector('.bear-web-x-container').textContent);
  const t1 = firstTextNode(p1);
  const t2 = firstTextNode(p2);
  const t3 = firstTextNode(p3);

  selectRange(t1, 0, t1, 4);
  await sleep(180);
  assert('selection enables apply-to-selection', applySel.disabled === false, 'button still disabled');

  setSelect(font, 'kaiti');
  setSelect(size, '24');
  applySel.click();
  await sleep(180);

  const marks1 = p1.querySelectorAll('.fft-sel-mark');
  const mark1 = marks1[0];
  results.info.singleSelection = {
    marks: marks1.length,
    text: mark1 ? mark1.textContent : null,
    fontSize: mark1 ? getComputedStyle(mark1).fontSize : null,
    fontFamily: mark1 ? getComputedStyle(mark1).fontFamily.split(',')[0] : null,
    p1Text: p1.textContent
  };
  assert('single selection wrapped exactly', marks1.length === 1 && mark1.textContent === '这是第一', JSON.stringify(results.info.singleSelection));
  assert('selection font size 24px', mark1 && getComputedStyle(mark1).fontSize === '24px', results.info.singleSelection.fontSize);
  assert('selection font family KaiTi', mark1 && /KaiTi|Kaiti/i.test(getComputedStyle(mark1).fontFamily), results.info.singleSelection.fontFamily);
  assert('unselected text remains 16px', getComputedStyle(p1).fontSize === '16px', getComputedStyle(p1).fontSize);

  clearSel.click();
  await sleep(120);
  assert('clear selection marks', document.querySelectorAll('.fft-sel-mark').length === 0, document.querySelectorAll('.fft-sel-mark').length);
  assert('text preserved after clear', norm(document.querySelector('.bear-web-x-container').textContent) === beforeAll, 'text changed');

  selectRange(t2, 2, t3, 6);
  await sleep(180);
  setSelect(font, '');
  setSelect(size, '18');
  applySel.click();
  await sleep(180);

  const marks2 = document.querySelectorAll('.fft-sel-mark');
  results.info.multiSelection = {
    marks: marks2.length,
    p2Marks: p2.querySelectorAll('.fft-sel-mark').length,
    p3Marks: p3.querySelectorAll('.fft-sel-mark').length,
    textPreserved: norm(document.querySelector('.bear-web-x-container').textContent) === beforeAll
  };
  assert('cross-paragraph selection wraps both paragraphs', p2.querySelectorAll('.fft-sel-mark').length >= 1 && p3.querySelectorAll('.fft-sel-mark').length >= 1, JSON.stringify(results.info.multiSelection));
  assert('cross-paragraph text preserved', results.info.multiSelection.textPreserved, 'text changed');

  clearSel.click();
  await sleep(120);

  setSelect(font, 'simsun');
  setSelect(size, '20');
  applyAll.click();
  await sleep(350);

  const bodyLine = p1;
  const sizeOf = (el) => getComputedStyle(el).fontSize;
  const familyOf = (el) => getComputedStyle(el).fontFamily.split(',')[0].replace(/["']/g, '');
  results.info.global = {
    body: sizeOf(bodyLine),
    h2: sizeOf(h2),
    title: sizeOf(title),
    code: sizeOf(code),
    bodyFamily: familyOf(bodyLine),
    codeFamily: familyOf(code),
    rootClass: document.documentElement.className,
    status: status.textContent
  };
  assert('global body 20px', sizeOf(bodyLine) === '20px', results.info.global.body);
  assert('heading keeps hierarchy 27.5px', sizeOf(h2) === '27.5px', results.info.global.h2);
  assert('title keeps hierarchy 42.5px', sizeOf(title) === '42.5px', results.info.global.title);
  assert('global font applied', /SimSun/i.test(getComputedStyle(bodyLine).fontFamily), results.info.global.bodyFamily);
  assert('code stays monospace', /SFMono|Consolas|Menlo/i.test(getComputedStyle(code).fontFamily), results.info.global.codeFamily);
  assert('global classes on html', /fft-font-on/.test(results.info.global.rootClass) && /fft-size-on/.test(results.info.global.rootClass), results.info.global.rootClass);
  assert('status reports scaling', /正文 16px → 20px/.test(results.info.global.status), results.info.global.status);

  reset.click();
  await sleep(180);
  results.info.reset = {
    body: sizeOf(p1),
    h2: sizeOf(h2),
    title: sizeOf(title),
    rootClass: document.documentElement.className,
    marks: document.querySelectorAll('.fft-sel-mark').length,
    status: status.textContent
  };
  assert('reset restores body', results.info.reset.body === '16px', results.info.reset.body);
  assert('reset restores heading', results.info.reset.h2 === '22px', results.info.reset.h2);
  assert('reset restores title', results.info.reset.title === '34px', results.info.reset.title);
  assert('reset removes html classes', !/fft-(font|size)-on/.test(results.info.reset.rootClass), results.info.reset.rootClass);
  assert('reset removes marks', results.info.reset.marks === 0, results.info.reset.marks);

  results.info.note = sr.querySelector('.fft-note') ? sr.querySelector('.fft-note').textContent : '';
  assert('local-only notice present', /不会修改云端文档/.test(results.info.note), results.info.note);

  return JSON.stringify(results);
})()
