// ==UserScript==
// @name         飞书文档字体助手
// @namespace    https://github.com/feishu-font-tool
// @version      1.0.0
// @description  调整网页版飞书文档的字体与字号：整篇缩放保留标题层级，也可只改选中文字。仅改变本机显示。
// @author       feishu-font-tool
// @license      MIT
// @match        https://*.feishu.cn/*
// @match        https://feishu.cn/*
// @match        https://*.larksuite.com/*
// @match        https://larksuite.com/*
// @match        https://*.larkoffice.com/*
// @match        https://larkoffice.com/*
// @run-at       document-start
// @grant        GM_getValue
// @grant        GM_setValue
// @grant        GM_registerMenuCommand
// @grant        GM_addStyle
// @noframes
// ==/UserScript==

(function () {
  'use strict';

  /* ------------------------------------------------------------------ *
   * 配置
   * ------------------------------------------------------------------ */

  const STORE_KEY = 'fft-settings-v1';
  const DOC_PATH_RE = /\/(docx|docs|wiki)(\/|$)/i;

  const DOC_ROOT_SELECTORS = [
    '.bear-web-x-container',
    '.lark-editor-render',
    '.docx-editor',
    '#docx'
  ];

  const DOC_ROOT_CSS = ':is(.bear-web-x-container, .lark-editor-render, .docx-editor, #docx)';

  const FONTS = [
    { id: '', label: '跟随文档', stack: '' },
    { id: 'system', label: '系统默认', stack: '-apple-system, BlinkMacSystemFont, "Segoe UI", "PingFang SC", "Microsoft YaHei", sans-serif' },
    { id: 'yahei', label: '微软雅黑', stack: '"Microsoft YaHei", "PingFang SC", "Noto Sans SC", sans-serif' },
    { id: 'pingfang', label: '苹方', stack: '"PingFang SC", "Microsoft YaHei", "Noto Sans SC", sans-serif' },
    { id: 'sourcehan-sans', label: '思源黑体', stack: '"Source Han Sans SC", "Noto Sans SC", "PingFang SC", "Microsoft YaHei", sans-serif' },
    { id: 'noto-sans', label: 'Noto Sans SC', stack: '"Noto Sans SC", "PingFang SC", "Microsoft YaHei", sans-serif' },
    { id: 'simhei', label: '黑体', stack: '"SimHei", "Heiti SC", "Noto Sans SC", sans-serif' },
    { id: 'simsun', label: '宋体', stack: '"SimSun", "Songti SC", "Noto Serif SC", serif' },
    { id: 'sourcehan-serif', label: '思源宋体', stack: '"Source Han Serif SC", "Noto Serif SC", "Songti SC", "SimSun", serif' },
    { id: 'noto-serif', label: 'Noto Serif SC', stack: '"Noto Serif SC", "Songti SC", "SimSun", serif' },
    { id: 'kaiti', label: '楷体', stack: '"KaiTi", "Kaiti SC", "STKaiti", "Noto Serif SC", serif' },
    { id: 'fangsong', label: '仿宋', stack: '"FangSong", "FangSong_GB2312", "STFangsong", "Noto Serif SC", serif' },
    { id: 'dengxian', label: '等线', stack: '"DengXian", "Microsoft YaHei", "PingFang SC", sans-serif' },
    { id: 'lxgw', label: '霞鹜文楷', stack: '"LXGW WenKai", "LXGW WenKai Screen", "KaiTi", "Noto Serif SC", serif' },
    { id: 'times', label: 'Times New Roman', stack: '"Times New Roman", "Songti SC", "SimSun", serif' },
    { id: 'arial', label: 'Arial', stack: 'Arial, "Microsoft YaHei", "PingFang SC", sans-serif' },
    { id: 'georgia', label: 'Georgia', stack: 'Georgia, "Songti SC", "SimSun", serif' },
    { id: 'verdana', label: 'Verdana', stack: 'Verdana, "Microsoft YaHei", "PingFang SC", sans-serif' },
    { id: 'courier', label: 'Courier New', stack: '"Courier New", "Microsoft YaHei", monospace' },
    { id: 'custom', label: '自定义字体…', stack: '' }
  ];

  const FONT_MAP = Object.create(null);
  FONTS.forEach(function (font) { FONT_MAP[font.id] = font; });

  const SIZES = [12, 14, 16, 18, 20, 22, 24, 28, 32, 36, 42, 48, 56, 64];

  const PAGE_CSS = [
    'html.fft-font-on ' + DOC_ROOT_CSS + ' .ace-line,',
    'html.fft-font-on ' + DOC_ROOT_CSS + ' .ace-line span[data-string="true"],',
    'html.fft-font-on ' + DOC_ROOT_CSS + ' .ace-line a,',
    'html.fft-font-on ' + DOC_ROOT_CSS + ' .ace-line a span {',
    '  font-family: var(--fft-font) !important;',
    '}',
    'html.fft-font-on ' + DOC_ROOT_CSS + ' .docx-code-block .ace-line,',
    'html.fft-font-on ' + DOC_ROOT_CSS + ' .docx-code-block .ace-line span,',
    'html.fft-font-on ' + DOC_ROOT_CSS + ' .code-block .ace-line,',
    'html.fft-font-on ' + DOC_ROOT_CSS + ' .code-block .ace-line span,',
    'html.fft-font-on ' + DOC_ROOT_CSS + ' pre,',
    'html.fft-font-on ' + DOC_ROOT_CSS + ' code {',
    '  font-family: "SFMono-Regular", Consolas, "Liberation Mono", Menlo, monospace !important;',
    '}',
    'html.fft-size-on ' + DOC_ROOT_CSS + ' .ace-line {',
    '  font-size: calc(1em * var(--fft-scale, 1)) !important;',
    '  line-height: 1.6 !important;',
    '}',
    '.fft-sel-mark {',
    '  border-radius: 2px;',
    '}',
    '.fft-sel-mark.fft-flash {',
    '  animation: fft-flash 0.75s ease-out;',
    '}',
    '@keyframes fft-flash {',
    '  0% { background-color: rgba(51, 112, 255, 0.24); }',
    '  100% { background-color: transparent; }',
    '}'
  ].join('\n');

  const UI_CSS = String.raw`
    :host { all: initial; }
    *, *::before, *::after { box-sizing: border-box; }
    .fft-root {
      --fft-bg: rgba(255, 255, 255, 0.97);
      --fft-fg: #1f2329;
      --fft-muted: #646a73;
      --fft-line: #e3e5e8;
      --fft-field: #f5f6f7;
      --fft-field-hover: #eef0f2;
      --fft-primary: #3370ff;
      --fft-primary-hover: #245bdb;
      --fft-danger: #d83931;
      --fft-ok: #1a7f37;
      --fft-warn: #b25e09;
      --fft-shadow: 0 18px 52px rgba(31, 35, 41, 0.2), 0 2px 8px rgba(31, 35, 41, 0.08);
      position: fixed;
      inset: auto 0 0 auto;
      z-index: 2147483647;
      width: 0;
      height: 0;
      pointer-events: none;
      color: var(--fft-fg);
      font-family: -apple-system, BlinkMacSystemFont, "Segoe UI", "PingFang SC", "Microsoft YaHei", sans-serif;
      font-size: 14px;
      line-height: 1.4;
      -webkit-font-smoothing: antialiased;
      text-rendering: optimizeLegibility;
    }
    @media (prefers-color-scheme: dark) {
      .fft-root {
        --fft-bg: rgba(30, 32, 36, 0.97);
        --fft-fg: #e8e9eb;
        --fft-muted: #9b9fa6;
        --fft-line: #3a3d44;
        --fft-field: #25272c;
        --fft-field-hover: #2d3036;
        --fft-primary: #5b8cff;
        --fft-primary-hover: #7aa2ff;
        --fft-danger: #ff6b64;
        --fft-ok: #5ccf7a;
        --fft-warn: #ffb45c;
        --fft-shadow: 0 18px 52px rgba(0, 0, 0, 0.55), 0 2px 8px rgba(0, 0, 0, 0.3);
      }
    }
    .fft-fab {
      position: fixed;
      right: 22px;
      bottom: 22px;
      width: 48px;
      height: 48px;
      display: flex;
      align-items: center;
      justify-content: center;
      gap: 1px;
      padding: 0;
      border: 1px solid color-mix(in srgb, var(--fft-line) 75%, transparent);
      border-radius: 16px;
      background: var(--fft-bg);
      color: var(--fft-fg);
      box-shadow: 0 8px 28px rgba(31, 35, 41, 0.18), 0 1px 2px rgba(31, 35, 41, 0.1);
      backdrop-filter: blur(14px) saturate(1.1);
      cursor: pointer;
      pointer-events: auto;
      transition: transform 0.15s ease, box-shadow 0.15s ease;
    }
    .fft-fab:hover {
      transform: translateY(-2px);
      box-shadow: 0 12px 32px rgba(31, 35, 41, 0.24), 0 2px 6px rgba(31, 35, 41, 0.12);
    }
    .fft-fab:active { transform: translateY(0); }
    .fft-fab:focus-visible {
      outline: 3px solid color-mix(in srgb, var(--fft-primary) 35%, transparent);
      outline-offset: 2px;
    }
    .fft-fab .fft-a {
      font-size: 20px;
      font-weight: 650;
      letter-spacing: -0.8px;
      line-height: 1;
    }
    .fft-fab .fft-a-small {
      align-self: flex-end;
      margin-bottom: 12px;
      font-size: 12px;
      font-weight: 600;
      opacity: 0.55;
      line-height: 1;
    }
    .fft-panel {
      position: fixed;
      right: 22px;
      bottom: 82px;
      width: 336px;
      max-height: calc(100vh - 120px);
      overflow: auto;
      padding: 14px;
      border: 1px solid color-mix(in srgb, var(--fft-line) 80%, transparent);
      border-radius: 16px;
      background: var(--fft-bg);
      box-shadow: var(--fft-shadow);
      backdrop-filter: blur(22px) saturate(1.15);
      pointer-events: auto;
      animation: fft-panel-in 0.16s ease-out;
      overscroll-behavior: contain;
    }
    .fft-panel[hidden], .fft-fab[hidden], .fft-toast[hidden] { display: none !important; }
    @keyframes fft-panel-in {
      from { opacity: 0; transform: translateY(6px) scale(0.985); }
      to { opacity: 1; transform: translateY(0) scale(1); }
    }
    .fft-head {
      display: flex;
      align-items: center;
      justify-content: space-between;
      gap: 8px;
      margin-bottom: 14px;
    }
    .fft-title {
      display: flex;
      align-items: center;
      gap: 7px;
      min-width: 0;
      font-size: 14px;
      font-weight: 650;
      letter-spacing: 0.01em;
    }
    .fft-dot {
      width: 7px;
      height: 7px;
      border-radius: 50%;
      background: var(--fft-primary);
      box-shadow: 0 0 0 4px color-mix(in srgb, var(--fft-primary) 14%, transparent);
      flex: none;
    }
    .fft-local {
      padding: 2px 6px;
      border-radius: 5px;
      background: var(--fft-field);
      color: var(--fft-muted);
      font-size: 10px;
      font-weight: 500;
      line-height: 1.4;
    }
    .fft-icon-btn {
      width: 28px;
      height: 28px;
      display: grid;
      place-items: center;
      padding: 0;
      border: 0;
      border-radius: 8px;
      background: transparent;
      color: var(--fft-muted);
      font-size: 20px;
      line-height: 1;
      cursor: pointer;
    }
    .fft-icon-btn:hover { background: var(--fft-field); color: var(--fft-fg); }
    .fft-field {
      display: flex;
      align-items: center;
      gap: 10px;
      margin-bottom: 10px;
    }
    .fft-label {
      width: 44px;
      flex: none;
      color: var(--fft-muted);
      font-size: 13px;
    }
    .fft-label em {
      display: block;
      margin-top: 1px;
      color: var(--fft-muted);
      font-size: 10px;
      font-style: normal;
      opacity: 0.8;
      white-space: nowrap;
    }
    .fft-select, .fft-input {
      width: 100%;
      min-width: 0;
      height: 34px;
      padding: 0 10px;
      border: 1px solid var(--fft-line);
      border-radius: 9px;
      outline: none;
      background: var(--fft-field);
      color: var(--fft-fg);
      font: inherit;
      font-size: 13px;
      transition: border-color 0.12s ease, box-shadow 0.12s ease, background 0.12s ease;
    }
    .fft-select {
      flex: 1;
      padding-right: 26px;
      appearance: none;
      background-image: linear-gradient(45deg, transparent 50%, var(--fft-muted) 50%), linear-gradient(135deg, var(--fft-muted) 50%, transparent 50%);
      background-position: calc(100% - 14px) 14px, calc(100% - 9px) 14px;
      background-size: 5px 5px, 5px 5px;
      background-repeat: no-repeat;
      cursor: pointer;
    }
    .fft-select:hover, .fft-input:hover { background-color: var(--fft-field-hover); }
    .fft-select:focus, .fft-input:focus {
      border-color: var(--fft-primary);
      box-shadow: 0 0 0 3px color-mix(in srgb, var(--fft-primary) 14%, transparent);
      background-color: var(--fft-bg);
    }
    .fft-custom { margin: -4px 0 10px 54px; }
    .fft-custom[hidden] { display: none !important; }
    .fft-custom .fft-input { height: 32px; }
    .fft-actions {
      display: grid;
      grid-template-columns: 1fr 1fr;
      gap: 8px;
      margin-top: 14px;
    }
    .fft-btn {
      height: 36px;
      padding: 0 10px;
      border: 1px solid var(--fft-line);
      border-radius: 9px;
      background: var(--fft-field);
      color: var(--fft-fg);
      font: inherit;
      font-size: 13px;
      font-weight: 500;
      cursor: pointer;
      transition: background 0.12s ease, border-color 0.12s ease, transform 0.08s ease;
      white-space: nowrap;
    }
    .fft-btn:hover:not(:disabled) { background: var(--fft-field-hover); }
    .fft-btn:active:not(:disabled) { transform: scale(0.985); }
    .fft-btn:focus-visible {
      outline: 3px solid color-mix(in srgb, var(--fft-primary) 25%, transparent);
      outline-offset: 1px;
    }
    .fft-btn:disabled { opacity: 0.45; cursor: not-allowed; }
    .fft-primary {
      border-color: var(--fft-primary);
      background: var(--fft-primary);
      color: #fff;
    }
    .fft-primary:hover:not(:disabled) { background: var(--fft-primary-hover); border-color: var(--fft-primary-hover); }
    .fft-status {
      min-height: 38px;
      margin-top: 10px;
      padding: 9px 10px;
      border-radius: 9px;
      background: var(--fft-field);
      color: var(--fft-muted);
      font-size: 12px;
      line-height: 1.55;
      overflow-wrap: anywhere;
    }
    .fft-status[data-tone="ok"] {
      background: color-mix(in srgb, var(--fft-ok) 9%, var(--fft-field));
      color: var(--fft-ok);
    }
    .fft-status[data-tone="warn"] {
      background: color-mix(in srgb, var(--fft-warn) 10%, var(--fft-field));
      color: var(--fft-warn);
    }
    .fft-status[data-tone="error"] {
      background: color-mix(in srgb, var(--fft-danger) 9%, var(--fft-field));
      color: var(--fft-danger);
    }
    .fft-foot {
      display: flex;
      align-items: center;
      flex-wrap: wrap;
      gap: 7px 12px;
      margin-top: 10px;
      font-size: 12px;
    }
    .fft-check {
      display: flex;
      align-items: center;
      gap: 5px;
      color: var(--fft-muted);
      cursor: pointer;
      user-select: none;
    }
    .fft-check input {
      width: 13px;
      height: 13px;
      margin: 0;
      accent-color: var(--fft-primary);
      cursor: pointer;
    }
    .fft-link {
      padding: 0;
      border: 0;
      background: none;
      color: var(--fft-muted);
      font: inherit;
      font-size: 12px;
      cursor: pointer;
      text-decoration: underline;
      text-underline-offset: 2px;
    }
    .fft-link:hover { color: var(--fft-fg); }
    .fft-link.fft-danger:hover { color: var(--fft-danger); }
    .fft-note {
      display: flex;
      gap: 6px;
      margin: 11px 0 0;
      color: var(--fft-muted);
      font-size: 11px;
      line-height: 1.55;
      opacity: 0.9;
    }
    .fft-note::before { content: "ⓘ"; flex: none; opacity: 0.8; }
    .fft-toast {
      position: fixed;
      top: 24px;
      left: 50%;
      transform: translateX(-50%);
      max-width: min(360px, calc(100vw - 32px));
      padding: 9px 13px;
      border: 1px solid rgba(255, 255, 255, 0.1);
      border-radius: 9px;
      background: rgba(24, 26, 30, 0.94);
      color: #fff;
      box-shadow: 0 10px 30px rgba(0, 0, 0, 0.25);
      font-size: 12px;
      line-height: 1.5;
      pointer-events: none;
      animation: fft-toast-in 0.18s ease-out;
      z-index: 2147483647;
    }
    @keyframes fft-toast-in {
      from { opacity: 0; transform: translate(-50%, -6px); }
      to { opacity: 1; transform: translate(-50%, 0); }
    }
    @media (max-width: 540px) {
      .fft-panel { right: 12px; bottom: 74px; width: calc(100vw - 24px); }
      .fft-fab { right: 14px; bottom: 14px; }
    }
  `;

  /* ------------------------------------------------------------------ *
   * 存储与状态
   * ------------------------------------------------------------------ */

  function gmGet(key, fallback) {
    try {
      if (typeof GM_getValue === 'function') return GM_getValue(key, fallback);
    } catch (err) { /* ignore */ }
    try {
      const raw = localStorage.getItem(key);
      return raw == null ? fallback : raw;
    } catch (err) {
      return fallback;
    }
  }

  function gmSet(key, value) {
    try {
      if (typeof GM_setValue === 'function') { GM_setValue(key, value); return; }
    } catch (err) { /* ignore */ }
    try { localStorage.setItem(key, value); } catch (err) { /* ignore */ }
  }

  function loadSettings() {
    let raw = gmGet(STORE_KEY, '');
    if (!raw) return {};
    try {
      const parsed = typeof raw === 'string' ? JSON.parse(raw) : raw;
      return parsed && typeof parsed === 'object' ? parsed : {};
    } catch (err) {
      return {};
    }
  }

  const saved = loadSettings();

  const state = {
    ui: {
      fontId: typeof saved.fontId === 'string' ? saved.fontId : '',
      customFont: typeof saved.customFont === 'string' ? saved.customFont : '',
      sizeId: typeof saved.sizeId === 'string' ? saved.sizeId : '',
      customSize: typeof saved.customSize === 'string' ? saved.customSize : ''
    },
    applied: saved.applied && (saved.applied.font || saved.applied.size)
      ? { font: saved.applied.font || '', size: Number(saved.applied.size) || 0 }
      : null,
    autoApply: saved.autoApply !== false
  };

  function persist() {
    gmSet(STORE_KEY, JSON.stringify({
      fontId: state.ui.fontId,
      customFont: state.ui.customFont,
      sizeId: state.ui.sizeId,
      customSize: state.ui.customSize,
      applied: state.applied,
      autoApply: state.autoApply
    }));
  }

  /* ------------------------------------------------------------------ *
   * 页面工具
   * ------------------------------------------------------------------ */

  function isDocPage() {
    return DOC_PATH_RE.test(location.pathname);
  }

  function getDocRoot() {
    for (let i = 0; i < DOC_ROOT_SELECTORS.length; i += 1) {
      const root = document.querySelector(DOC_ROOT_SELECTORS[i]);
      if (root) return root;
    }
    return null;
  }

  function getDocLines() {
    const root = getDocRoot();
    if (root) return Array.from(root.querySelectorAll('.ace-line'));
    return Array.from(document.querySelectorAll('.ace-line'));
  }

  function clamp(value, min, max) {
    return Math.min(max, Math.max(min, value));
  }

  function formatPx(value) {
    const rounded = Math.round(value * 10) / 10;
    return String(rounded).replace(/\.0$/, '') + 'px';
  }

  function measureBasePx() {
    const lines = getDocLines().slice(0, 120);
    if (!lines.length) return 16;

    const html = document.documentElement;
    const hadSize = html.classList.contains('fft-size-on');
    const previousScale = html.style.getPropertyValue('--fft-scale');
    if (hadSize) html.style.setProperty('--fft-scale', '1');

    const sizes = [];
    const textSizes = [];
    const fallbackSizes = [];
    for (let i = 0; i < lines.length; i += 1) {
      const line = lines[i];
      const px = parseFloat(getComputedStyle(line).fontSize);
      if (!px || px <= 0) continue;
      fallbackSizes.push(px);
      if (line.closest('.heading, .page-block-content, .docx-code-block, .code-block')) continue;
      sizes.push(px);
      if (line.closest('.docx-text-block')) textSizes.push(px);
    }

    if (hadSize) {
      if (previousScale) html.style.setProperty('--fft-scale', previousScale);
      else html.style.removeProperty('--fft-scale');
    }

    const pool = textSizes.length ? textSizes : (sizes.length ? sizes : fallbackSizes);
    if (!pool.length) return 16;
    pool.sort(function (a, b) { return a - b; });
    return pool[Math.floor(pool.length / 2)] || 16;
  }

  function normalizeCustomFont(raw) {
    const text = String(raw || '').trim();
    if (!text || /[;{}<>]/.test(text)) return '';
    if (/[,"']/.test(text)) return text;
    if (/^(serif|sans-serif|monospace|cursive|fantasy|system-ui)$/i.test(text)) return text;
    return '"' + text.replace(/"/g, '') + '", sans-serif';
  }

  function parseCustomSize(raw) {
    const n = Number(String(raw || '').trim());
    if (!Number.isFinite(n)) return 0;
    return Math.round(clamp(n, 8, 96));
  }

  /* ------------------------------------------------------------------ *
   * 页面样式与整篇应用
   * ------------------------------------------------------------------ */

  function injectPageStyle() {
    try {
      if (typeof GM_addStyle === 'function') {
        GM_addStyle(PAGE_CSS);
        return;
      }
    } catch (err) { /* fall through */ }
    const style = document.createElement('style');
    style.id = 'fft-page-style';
    style.textContent = PAGE_CSS;
    (document.head || document.documentElement).appendChild(style);
  }

  function applyGlobal(options, opts) {
    const settings = opts || {};
    const font = options && options.font ? options.font : '';
    const size = options && options.size ? Number(options.size) : 0;

    if (!settings.auto) autoToken += 1;

    if (!font && !size) {
      clearAll();
      return { ok: true, empty: true };
    }

    if (!getDocRoot() && !document.querySelector('.ace-line')) {
      if (!settings.silent) notify('还没找到飞书文档正文，请等页面加载完成后再试。', 'warn', true);
      return { ok: false, reason: 'no-doc' };
    }

    const html = document.documentElement;

    if (font) {
      html.style.setProperty('--fft-font', font);
      html.classList.add('fft-font-on');
    } else {
      html.classList.remove('fft-font-on');
      html.style.removeProperty('--fft-font');
    }

    let base = 0;
    let scale = 0;
    if (size) {
      base = measureBasePx();
      scale = clamp(size / base, 0.4, 4);
      html.style.setProperty('--fft-scale', String(Math.round(scale * 1000) / 1000));
      html.classList.add('fft-size-on');
    } else {
      html.classList.remove('fft-size-on');
      html.style.removeProperty('--fft-scale');
    }

    state.applied = { font: font, size: size || 0 };
    persist();

    if (!settings.silent) {
      const parts = [];
      if (font) {
        const label = (FONTS.find(function (item) { return item.stack === font; }) || {}).label;
        parts.push(label && label !== '自定义字体…' ? label : '自定义字体');
      }
      if (size) parts.push('正文 ' + formatPx(base) + ' → ' + formatPx(size));
      const text = '已应用到全文：' + parts.join(' · ') + (size ? '（标题按比例缩放）' : '');
      notify(text, 'ok', false);
      if (ui.baseHint) updateHints();
    }

    return { ok: true, base: base, scale: scale };
  }

  function clearAll() {
    autoToken += 1;
    const html = document.documentElement;
    html.classList.remove('fft-font-on', 'fft-size-on');
    html.style.removeProperty('--fft-font');
    html.style.removeProperty('--fft-scale');
    clearSelectionMarks(true);
    state.applied = null;
    persist();
    if (ui.status) {
      notify('已恢复飞书文档的默认字体与字号。', 'ok', true);
    }
  }

  /* ------------------------------------------------------------------ *
   * 选区样式
   * ------------------------------------------------------------------ */

  let savedRange = null;
  let rangeTimer = 0;

  function isRangeInDoc(range) {
    const root = getDocRoot();
    if (!root || !range) return false;
    try {
      return root.contains(range.commonAncestorContainer);
    } catch (err) {
      return false;
    }
  }

  function captureSelection() {
    const selection = window.getSelection();
    if (!selection || !selection.rangeCount) return;
    const range = selection.getRangeAt(0);
    if (range.collapsed || !isRangeInDoc(range)) return;
    try {
      savedRange = range.cloneRange();
    } catch (err) {
      savedRange = null;
    }
    refreshSelectionButton();
  }

  function onSelectionChange() {
    window.clearTimeout(rangeTimer);
    rangeTimer = window.setTimeout(captureSelection, 60);
  }

  function getActionRange() {
    const selection = window.getSelection();
    if (selection && selection.rangeCount) {
      const live = selection.getRangeAt(0);
      if (!live.collapsed && isRangeInDoc(live)) return live.cloneRange();
    }
    if (savedRange && !savedRange.collapsed && isRangeInDoc(savedRange)) {
      if (savedRange.startContainer && savedRange.startContainer.isConnected) {
        return savedRange.cloneRange();
      }
    }
    return null;
  }

  function refreshSelectionButton() {
    if (!ui.applySel) return;
    const range = getActionRange();
    ui.applySel.disabled = !range;
    ui.applySel.title = range ? '把当前字体/字号应用到选中的文字' : '请先在文档中选中文字';
  }

  function styleMark(mark, options) {
    if (options.font) mark.style.setProperty('font-family', options.font, 'important');
    else mark.style.removeProperty('font-family');

    if (options.size) {
      mark.style.setProperty('font-size', options.size + 'px', 'important');
      mark.style.setProperty('line-height', '1.6', 'important');
    } else {
      mark.style.removeProperty('font-size');
      mark.style.removeProperty('line-height');
    }
  }

  function unwrapMark(mark) {
    const parent = mark.parentNode;
    if (!parent) return;
    while (mark.firstChild) parent.insertBefore(mark.firstChild, mark);
    parent.removeChild(mark);
  }

  function applySelection(options) {
    const range = getActionRange();
    if (!range) {
      notify('请先在飞书文档中选中一段文字，再点“应用到选区”。', 'warn', true);
      return { ok: false, reason: 'no-range' };
    }
    if (!options.font && !options.size) {
      notify('请先选择字体或字号。', 'warn', true);
      return { ok: false, reason: 'empty' };
    }

    const startNode = range.startContainer;
    if (startNode && startNode.isConnected === false) {
      savedRange = null;
      refreshSelectionButton();
      notify('选中的内容已经刷新，请重新选择文字。', 'warn', true);
      return { ok: false, reason: 'stale' };
    }

    const root = range.commonAncestorContainer.nodeType === Node.TEXT_NODE
      ? range.commonAncestorContainer.parentNode
      : range.commonAncestorContainer;

    const textNodes = [];
    const walker = document.createTreeWalker(root, NodeFilter.SHOW_TEXT, {
      acceptNode: function (node) {
        if (!node.nodeValue || !node.nodeValue.trim()) return NodeFilter.FILTER_REJECT;
        if (/^[\u200b\u200c\u200d\ufeff]+$/.test(node.nodeValue)) return NodeFilter.FILTER_REJECT;
        if (!node.parentElement) return NodeFilter.FILTER_REJECT;
        if (node.parentElement.closest('script, style, textarea, #fft-ui-host')) return NodeFilter.FILTER_REJECT;
        try {
          if (!range.intersectsNode(node)) return NodeFilter.FILTER_REJECT;
        } catch (err) {
          return NodeFilter.FILTER_REJECT;
        }
        return NodeFilter.FILTER_ACCEPT;
      }
    });

    let node;
    while ((node = walker.nextNode())) textNodes.push(node);

    if (!textNodes.length) {
      notify('选中的区域里没有可调整的文字。', 'warn', true);
      return { ok: false, reason: 'no-text' };
    }

    const marks = new Set();
    let count = 0;

    for (let i = textNodes.length - 1; i >= 0; i -= 1) {
      const text = textNodes[i];
      let start = text === range.startContainer ? range.startOffset : 0;
      let end = text === range.endContainer ? range.endOffset : text.length;
      if (start < 0) start = 0;
      if (end > text.length) end = text.length;
      if (start >= end) continue;

      const existing = text.parentElement && text.parentElement.closest('.fft-sel-mark');
      if (existing && existing.contains(text)) {
        styleMark(existing, options);
        marks.add(existing);
        count += 1;
        continue;
      }

      let target = text;
      try {
        if (start > 0) target = target.splitText(start);
        if (end - start < target.length) target.splitText(end - start);
      } catch (err) {
        continue;
      }

      if (!target.parentNode) continue;
      const mark = document.createElement('span');
      mark.className = 'fft-sel-mark';
      mark.setAttribute('data-fft-mark', '1');
      styleMark(mark, options);
      target.parentNode.insertBefore(mark, target);
      mark.appendChild(target);
      marks.add(mark);
      count += 1;
    }

    if (!count) {
      notify('没有找到可调整的文字，请重新选择。', 'warn', true);
      return { ok: false, reason: 'no-text' };
    }

    marks.forEach(function (mark) {
      mark.classList.add('fft-flash');
      window.setTimeout(function () { mark.classList.remove('fft-flash'); }, 800);
    });

    savedRange = null;
    refreshSelectionButton();

    const changed = [];
    if (options.font) changed.push('字体');
    if (options.size) changed.push(formatPx(options.size));
    notify('已应用选区样式：' + changed.join(' · ') + '，共 ' + count + ' 处文字。', 'ok', false);
    if (ui.baseHint && options.size) ui.baseHint.textContent = '选区 ' + formatPx(options.size);
    return { ok: true, count: count };
  }

  function clearSelectionMarks(silent) {
    const marks = document.querySelectorAll('.fft-sel-mark');
    for (let i = 0; i < marks.length; i += 1) unwrapMark(marks[i]);
    if (!silent) {
      if (marks.length) notify('已清除选区样式，共恢复 ' + marks.length + ' 处文字。', 'ok', false);
      else notify('当前没有选区样式需要清除。', '', false);
    }
    return marks.length;
  }

  /* ------------------------------------------------------------------ *
   * UI
   * ------------------------------------------------------------------ */

  let host = null;
  let shadow = null;
  let panel = null;
  let fab = null;
  let toast = null;
  let toastTimer = 0;

  const ui = {
    font: null,
    fontCustomWrap: null,
    fontCustom: null,
    size: null,
    sizeCustomWrap: null,
    sizeCustom: null,
    applyAll: null,
    applySel: null,
    clearSel: null,
    reset: null,
    auto: null,
    baseHint: null,
    status: null
  };

  function buildOptions() {
    const fontGroups = [
      { label: '跟随 / 通用', ids: ['', 'system'] },
      { label: '中文字体', ids: ['yahei', 'pingfang', 'sourcehan-sans', 'noto-sans', 'simhei', 'simsun', 'sourcehan-serif', 'noto-serif', 'kaiti', 'fangsong', 'dengxian', 'lxgw'] },
      { label: '西文字体', ids: ['times', 'arial', 'georgia', 'verdana', 'courier'] },
      { label: '其他', ids: ['custom'] }
    ];
    fontGroups.forEach(function (group) {
      const optgroup = document.createElement('optgroup');
      optgroup.label = group.label;
      group.ids.forEach(function (id) {
        const font = FONT_MAP[id];
        if (!font) return;
        const option = document.createElement('option');
        option.value = font.id;
        option.textContent = font.label;
        optgroup.appendChild(option);
      });
      ui.font.appendChild(optgroup);
    });

    const defaultOption = document.createElement('option');
    defaultOption.value = '';
    defaultOption.textContent = '跟随文档';
    ui.size.appendChild(defaultOption);

    SIZES.forEach(function (size) {
      const option = document.createElement('option');
      option.value = String(size);
      option.textContent = size + ' px';
      ui.size.appendChild(option);
    });

    const customOption = document.createElement('option');
    customOption.value = 'custom';
    customOption.textContent = '自定义…';
    ui.size.appendChild(customOption);
  }

  function makeUI() {
    if (host) return true;
    if (!document.body && !document.documentElement) return false;

    host = document.createElement('div');
    host.id = 'fft-ui-host';
    host.style.cssText = 'position:fixed;inset:auto 0 0 auto;width:0;height:0;z-index:2147483647;pointer-events:none;';
    (document.body || document.documentElement).appendChild(host);
    shadow = host.attachShadow({ mode: 'open' });

    const style = document.createElement('style');
    style.textContent = UI_CSS;
    shadow.appendChild(style);

    const root = document.createElement('div');
    root.className = 'fft-root';
    root.innerHTML = [
      '<button class="fft-fab" id="fft-fab" type="button" title="飞书字体助手" aria-label="打开飞书字体助手" aria-expanded="false">',
      '  <span class="fft-a">A</span><span class="fft-a-small">a</span>',
      '</button>',
      '<section class="fft-panel" id="fft-panel" role="dialog" aria-label="飞书字体设置" hidden>',
      '  <header class="fft-head">',
      '    <div class="fft-title"><span class="fft-dot"></span>飞书字体助手<span class="fft-local">仅本机</span></div>',
      '    <button class="fft-icon-btn" id="fft-close" type="button" title="收起面板" aria-label="收起面板">×</button>',
      '  </header>',
      '  <div class="fft-field">',
      '    <label class="fft-label" for="fft-font">字体</label>',
      '    <select class="fft-select" id="fft-font"></select>',
      '  </div>',
      '  <div class="fft-custom" id="fft-font-custom-wrap" hidden>',
      '    <input class="fft-input" id="fft-font-custom" type="text" spellcheck="false" placeholder="字体名称，例如 LXGW WenKai">',
      '  </div>',
      '  <div class="fft-field">',
      '    <label class="fft-label" for="fft-size">字号<em id="fft-base-hint">正文 --</em></label>',
      '    <select class="fft-select" id="fft-size"></select>',
      '  </div>',
      '  <div class="fft-custom" id="fft-size-custom-wrap" hidden>',
      '    <input class="fft-input" id="fft-size-custom" type="number" min="8" max="96" step="1" placeholder="8–96 px">',
      '  </div>',
      '  <div class="fft-actions">',
      '    <button class="fft-btn fft-primary" id="fft-apply-all" type="button">应用到全文</button>',
      '    <button class="fft-btn" id="fft-apply-sel" type="button" disabled title="请先在文档中选中文字">应用到选区</button>',
      '  </div>',
      '  <div class="fft-status" id="fft-status" data-tone="">选择字体或字号后应用；整篇调字号会按正文基准缩放并保留标题层级。</div>',
      '  <div class="fft-foot">',
      '    <label class="fft-check"><input type="checkbox" id="fft-auto"> 新文档自动应用</label>',
      '    <button class="fft-link" id="fft-clear-sel" type="button">清除选区样式</button>',
      '    <button class="fft-link fft-danger" id="fft-reset" type="button">全部重置</button>',
      '  </div>',
      '  <p class="fft-note">只改变本机显示，不会修改云端文档，也不影响协作方。选区样式在飞书重绘后可能需要重新应用。</p>',
      '</section>',
      '<div class="fft-toast" id="fft-toast" hidden></div>'
    ].join('\n');
    shadow.appendChild(root);

    fab = shadow.getElementById('fft-fab');
    panel = shadow.getElementById('fft-panel');
    toast = shadow.getElementById('fft-toast');
    ui.font = shadow.getElementById('fft-font');
    ui.fontCustomWrap = shadow.getElementById('fft-font-custom-wrap');
    ui.fontCustom = shadow.getElementById('fft-font-custom');
    ui.size = shadow.getElementById('fft-size');
    ui.sizeCustomWrap = shadow.getElementById('fft-size-custom-wrap');
    ui.sizeCustom = shadow.getElementById('fft-size-custom');
    ui.applyAll = shadow.getElementById('fft-apply-all');
    ui.applySel = shadow.getElementById('fft-apply-sel');
    ui.clearSel = shadow.getElementById('fft-clear-sel');
    ui.reset = shadow.getElementById('fft-reset');
    ui.auto = shadow.getElementById('fft-auto');
    ui.baseHint = shadow.getElementById('fft-base-hint');
    ui.status = shadow.getElementById('fft-status');

    buildOptions();
    restoreUI();
    bindUI();
    refreshSelectionButton();
    return true;
  }

  function restoreUI() {
    ui.font.value = FONT_MAP[state.ui.fontId] ? state.ui.fontId : '';
    ui.fontCustom.value = state.ui.customFont || '';
    ui.fontCustomWrap.hidden = ui.font.value !== 'custom';

    const sizeId = state.ui.sizeId;
    if (sizeId === 'custom' || SIZES.indexOf(Number(sizeId)) !== -1) ui.size.value = sizeId;
    else ui.size.value = '';
    ui.sizeCustom.value = state.ui.customSize || '';
    ui.sizeCustomWrap.hidden = ui.size.value !== 'custom';

    ui.auto.checked = Boolean(state.autoApply);
    updateHints();
  }

  function updateHints() {
    if (!ui.baseHint) return;
    if (!getDocRoot() && !document.querySelector('.ace-line')) {
      ui.baseHint.textContent = '正文 --';
      return;
    }
    const base = measureBasePx();
    const target = readSize();
    ui.baseHint.textContent = target
      ? '正文 ' + formatPx(base) + ' → ' + formatPx(target)
      : '正文 ' + formatPx(base);
  }

  function readFont() {
    const id = ui.font.value;
    if (id === 'custom') return normalizeCustomFont(ui.fontCustom.value);
    const font = FONT_MAP[id];
    return font ? font.stack : '';
  }

  function readSize() {
    const id = ui.size.value;
    if (id === 'custom') {
      const value = parseCustomSize(ui.sizeCustom.value);
      return value || 0;
    }
    if (id) return Number(id) || 0;
    return 0;
  }

  function readOptions() {
    return { font: readFont(), size: readSize() };
  }

  function setStatus(text, tone) {
    if (!ui.status) return;
    ui.status.textContent = text;
    ui.status.setAttribute('data-tone', tone || '');
  }

  function notify(text, tone, toastToo) {
    setStatus(text, tone);
    if (!toast) return;
    if (toastToo || panel.hidden) {
      window.clearTimeout(toastTimer);
      toast.textContent = text;
      toast.hidden = false;
      toast.style.animation = 'none';
      void toast.offsetWidth;
      toast.style.animation = '';
      toastTimer = window.setTimeout(function () { toast.hidden = true; }, 2600);
    }
  }

  function openPanel() {
    if (!makeUI()) return;
    panel.hidden = false;
    fab.hidden = true;
    fab.setAttribute('aria-expanded', 'true');
    updateHints();
    refreshSelectionButton();
  }

  function closePanel() {
    if (!panel) return;
    panel.hidden = true;
    fab.hidden = !isDocPage();
    fab.setAttribute('aria-expanded', 'false');
  }

  function togglePanel() {
    if (!isDocPage()) return;
    if (!makeUI()) return;
    if (panel.hidden) openPanel();
    else closePanel();
  }

  function bindUI() {
    fab.addEventListener('mousedown', function (event) {
      event.preventDefault();
      event.stopPropagation();
    });
    fab.addEventListener('click', function (event) {
      event.stopPropagation();
      openPanel();
    });

    const closeBtn = shadow.getElementById('fft-close');
    closeBtn.addEventListener('mousedown', function (event) {
      event.preventDefault();
      event.stopPropagation();
    });
    closeBtn.addEventListener('click', function (event) {
      event.stopPropagation();
      closePanel();
    });

    panel.addEventListener('mousedown', function (event) {
      event.stopPropagation();
      if (event.target.closest('select, input, textarea, option')) return;
      event.preventDefault();
    });
    panel.addEventListener('pointerdown', function (event) {
      event.stopPropagation();
    });
    panel.addEventListener('click', function (event) {
      event.stopPropagation();
    });
    panel.addEventListener('wheel', function (event) {
      event.stopPropagation();
    }, { passive: true });
    panel.addEventListener('keydown', function (event) {
      event.stopPropagation();
      if (event.key === 'Escape') closePanel();
    });
    panel.addEventListener('keyup', function (event) {
      event.stopPropagation();
    });

    ui.font.addEventListener('change', function () {
      state.ui.fontId = ui.font.value;
      ui.fontCustomWrap.hidden = ui.font.value !== 'custom';
      if (ui.font.value === 'custom') window.setTimeout(function () { ui.fontCustom.focus(); }, 20);
      persist();
    });
    ui.fontCustom.addEventListener('input', function () {
      state.ui.customFont = ui.fontCustom.value;
      persist();
    });

    ui.size.addEventListener('change', function () {
      state.ui.sizeId = ui.size.value;
      ui.sizeCustomWrap.hidden = ui.size.value !== 'custom';
      if (ui.size.value === 'custom') window.setTimeout(function () { ui.sizeCustom.focus(); }, 20);
      persist();
      updateHints();
    });
    ui.sizeCustom.addEventListener('input', function () {
      state.ui.customSize = ui.sizeCustom.value;
      persist();
      updateHints();
    });

    ui.auto.addEventListener('change', function () {
      state.autoApply = ui.auto.checked;
      persist();
      setStatus(state.autoApply ? '已开启：打开新文档时会自动套用上次的整篇设置。' : '已关闭新文档自动应用。', '');
    });

    ui.applyAll.addEventListener('click', function (event) {
      event.stopPropagation();
      const options = readOptions();
      if (ui.font.value === 'custom' && !options.font) {
        notify('请填写有效的自定义字体名称。', 'warn', true);
        ui.fontCustom.focus();
        return;
      }
      if (ui.size.value === 'custom' && !options.size) {
        notify('请填写 8–96 之间的字号。', 'warn', true);
        ui.sizeCustom.focus();
        return;
      }
      if (!options.font && !options.size) {
        notify('请先选择字体或字号。', 'warn', true);
        return;
      }
      const result = applyGlobal(options, {});
      if (result.ok && !result.empty) state.applied = options;
    });

    ui.applySel.addEventListener('click', function (event) {
      event.stopPropagation();
      const options = readOptions();
      if (ui.font.value === 'custom' && !options.font) {
        notify('请填写有效的自定义字体名称。', 'warn', true);
        ui.fontCustom.focus();
        return;
      }
      if (ui.size.value === 'custom' && !options.size) {
        notify('请填写 8–96 之间的字号。', 'warn', true);
        ui.sizeCustom.focus();
        return;
      }
      if (!options.font && !options.size) {
        notify('请先选择字体或字号。', 'warn', true);
        return;
      }
      applySelection(options);
    });

    ui.clearSel.addEventListener('click', function (event) {
      event.stopPropagation();
      clearSelectionMarks(false);
    });

    ui.reset.addEventListener('click', function (event) {
      event.stopPropagation();
      state.ui = { fontId: '', customFont: '', sizeId: '', customSize: '' };
      ui.font.value = '';
      ui.fontCustom.value = '';
      ui.fontCustomWrap.hidden = true;
      ui.size.value = '';
      ui.sizeCustom.value = '';
      ui.sizeCustomWrap.hidden = true;
      clearAll();
      updateHints();
      refreshSelectionButton();
    });

    document.addEventListener('selectionchange', onSelectionChange, true);
    document.addEventListener('mouseup', onSelectionChange, true);
    document.addEventListener('keyup', onSelectionChange, true);

    window.addEventListener('resize', function () {
      if (!panel.hidden) updateHints();
    }, { passive: true });
  }

  /* ------------------------------------------------------------------ *
   * 自动应用与 SPA 导航
   * ------------------------------------------------------------------ */

  let autoToken = 0;
  let lastHref = location.href;

  function scheduleAutoApply(delay) {
    const token = ++autoToken;
    if (!state.autoApply || !state.applied) return;

    let waited = 0;
    const started = Date.now();

    function attempt() {
      if (token !== autoToken) return;
      if (!state.autoApply || !state.applied) return;
      if (getDocRoot() && getDocLines().length) {
        window.setTimeout(function () {
          if (token !== autoToken) return;
          applyGlobal(state.applied, { silent: true, auto: true });
          if (ui.baseHint) updateHints();
          setStatus('已自动套用上次设置：' + describeApplied() + '。', '');
        }, 350);
        return;
      }
      if (Date.now() - started > 45000) {
        return;
      }
      waited += 1;
      window.setTimeout(attempt, waited < 20 ? 300 : 800);
    }

    window.setTimeout(attempt, delay == null ? 600 : delay);
  }

  function describeApplied() {
    if (!state.applied) return '';
    const parts = [];
    if (state.applied.font) {
      const found = FONTS.find(function (item) { return item.stack === state.applied.font; });
      parts.push(found && found.label !== '自定义字体…' ? found.label : '自定义字体');
    }
    if (state.applied.size) parts.push(formatPx(state.applied.size));
    return parts.join(' · ');
  }

  function watchNavigation() {
    window.setInterval(function () {
      if (location.href === lastHref) return;
      lastHref = location.href;
      savedRange = null;
      refreshSelectionButton();

      if (!isDocPage()) {
        if (panel) panel.hidden = true;
        if (fab) fab.hidden = true;
        return;
      }

      if (!host) {
        boot();
        return;
      }

      if (fab) fab.hidden = !panel.hidden;
      if (ui.baseHint) updateHints();
      if (state.autoApply && state.applied) scheduleAutoApply(1200);
    }, 1000);
  }

  /* ------------------------------------------------------------------ *
   * 启动
   * ------------------------------------------------------------------ */

  let booted = false;

  function boot() {
    if (!isDocPage()) return;
    if (!makeUI()) {
      window.setTimeout(boot, 100);
      return;
    }

    if (fab) fab.hidden = !panel.hidden;

    if (!booted) {
      booted = true;
      if (state.autoApply && state.applied) {
        scheduleAutoApply(900);
      } else {
        setStatus('选择字体或字号后应用；整篇调字号会按正文基准缩放并保留标题层级。', '');
      }
      window.setTimeout(updateHints, 1500);
    }
  }

  function start() {
    injectPageStyle();

    if (document.readyState === 'loading') {
      document.addEventListener('DOMContentLoaded', boot, { once: true });
    } else {
      boot();
    }

    if (typeof GM_registerMenuCommand === 'function') {
      try {
        GM_registerMenuCommand('打开飞书字体面板', togglePanel);
      } catch (err) { /* ignore */ }
    }

    watchNavigation();
  }

  start();
})();
