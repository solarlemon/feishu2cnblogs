/* ============================================================
   飞书 → 博客园  前端逻辑
   原生 JS，无框架、无 CDN
   ============================================================ */
(() => {
  'use strict';

  const $ = (sel) => document.querySelector(sel);
  const $$ = (sel) => Array.from(document.querySelectorAll(sel));

  const state = {
    token: null,
    config: null,
    preview: null,
    jobTimer: null,
    jobId: null,
    categories: [],
    tags: [],
  };

  /* ---------------- 基础工具 ---------------- */

  const esc = (s) => String(s == null ? '' : s).replace(/[&<>"']/g, (c) => ({
    '&': '&amp;', '<': '&lt;', '>': '&gt;', '"': '&quot;', "'": '&#39;',
  }[c]));

  function toast(message, kind) {
    const el = document.createElement('div');
    el.className = 'toast' + (kind ? ' ' + kind : '');
    el.textContent = message;
    $('#toasts').appendChild(el);
    setTimeout(() => {
      el.style.transition = 'opacity .25s, transform .25s';
      el.style.opacity = '0';
      el.style.transform = 'translateY(6px)';
      setTimeout(() => el.remove(), 260);
    }, 2600);
  }

  async function copyText(text) {
    try {
      await navigator.clipboard.writeText(text);
      return true;
    } catch (e) {
      const area = document.createElement('textarea');
      area.value = text;
      area.style.position = 'fixed';
      area.style.opacity = '0';
      document.body.appendChild(area);
      area.select();
      let ok = false;
      try { ok = document.execCommand('copy'); } catch (err) { ok = false; }
      area.remove();
      return ok;
    }
  }

  async function api(path, body) {
    const opts = {
      method: body === undefined ? 'GET' : 'POST',
      headers: { 'X-Token': state.token || '' },
    };
    if (body !== undefined) {
      opts.headers['Content-Type'] = 'application/json';
      opts.body = JSON.stringify(body);
    }
    const res = await fetch(path, opts);
    let data;
    try {
      data = await res.json();
    } catch (e) {
      throw new Error('服务返回异常（HTTP ' + res.status + '）');
    }
    if (!data.ok) throw new Error(data.error || '请求失败');
    return data;
  }

  function setBusy(btn, busy, label) {
    const spinner = btn.querySelector('.spinner');
    const text = btn.querySelector('.btn-label');
    btn.disabled = busy;
    if (spinner) spinner.hidden = !busy;
    if (text && label) text.textContent = label;
  }

  /* ---------------- Markdown 渲染（独立文件，便于测试） ---------------- */

  const renderMarkdown = window.F2CMarkdown.renderMarkdown;

  /* ---------------- 标签 chips ---------------- */

  function Chips(container, values, onChange) {
    const input = container.querySelector('input');
    let list = (values || []).slice();

    function render() {
      Array.from(container.querySelectorAll('.chip')).forEach((el) => el.remove());
      list.forEach((value, index) => {
        const chip = document.createElement('span');
        chip.className = 'chip';
        chip.innerHTML = '<span></span><button type="button" title="移除">✕</button>';
        chip.firstChild.textContent = value;
        chip.querySelector('button').addEventListener('click', () => {
          list.splice(index, 1);
          render();
          onChange(list.slice());
        });
        container.insertBefore(chip, input);
      });
    }

    function add(raw) {
      String(raw).replace(/，/g, ',').split(',').forEach((piece) => {
        const value = piece.trim();
        if (value && list.indexOf(value) === -1) list.push(value);
      });
      input.value = '';
      render();
      onChange(list.slice());
    }

    input.addEventListener('keydown', (e) => {
      if (e.key === 'Enter' || e.key === ',' || e.key === '，') {
        e.preventDefault();
        if (input.value.trim()) add(input.value);
      } else if (e.key === 'Backspace' && !input.value && list.length) {
        list.pop();
        render();
        onChange(list.slice());
      }
    });
    input.addEventListener('blur', () => { if (input.value.trim()) add(input.value); });

    render();
    return {
      set(values) { list = (values || []).slice(); render(); },
      get() { return list.slice(); },
    };
  }

  let chipsCategories = null;
  let chipsTags = null;

  /* ---------------- 配置 ---------------- */

  async function refreshConfig() {
    const cfg = await api('/api/config');
    state.config = cfg;
    const setDot = (side, ok) => {
      const dot = $('.dot[data-side="' + side + '"]');
      if (dot) {
        dot.classList.toggle('on', !!ok);
        dot.classList.toggle('off', !ok);
        dot.title = ok ? '已配置' : '未配置';
      }
    };
    setDot('feishu', cfg.feishu.ready);
    setDot('cnblogs', cfg.cnblogs.ready);

    $('#cfgPath').textContent = cfg.config_path;

    if (chipsCategories && cfg.cnblogs.categories && !chipsCategories.get().length) {
      chipsCategories.set(cfg.cnblogs.categories);
    }
    if (chipsTags && cfg.cnblogs.tags && !chipsTags.get().length) {
      chipsTags.set(cfg.cnblogs.tags);
    }

    // 设置弹窗里回填（敏感项用掩码占位，留空表示不修改）
    $('#setAppId').value = cfg.feishu.app_id || '';
    $('#setAppSecret').value = '';
    $('#setAppSecret').placeholder = cfg.feishu.has_secret ? ('已保存：' + cfg.feishu.app_secret) : 'App Secret';
    $('#setUserToken').value = '';
    $('#setUserToken').placeholder = cfg.feishu.has_user_token ? ('已保存：' + cfg.feishu.user_token) : '可选';
    $('#setUsername').value = cfg.cnblogs.username || '';
    $('#setBlog').value = cfg.cnblogs.blog || '';
    $('#setToken').value = '';
    $('#setToken').placeholder = cfg.cnblogs.has_token ? ('已保存：' + cfg.cnblogs.token) : '访问令牌';
    $('#setCategories').value = (cfg.cnblogs.categories || []).join(',');
    $('#setTags').value = (cfg.cnblogs.tags || []).join(',');
    return cfg;
  }

  /* ---------------- 预览 ---------------- */

  function renderWarnings(container, warnings) {
    container.innerHTML = '';
    (warnings || []).forEach((w) => {
      const item = document.createElement('div');
      item.className = 'warn-item';
      item.innerHTML = '<span>⚠</span><span></span>';
      item.lastChild.textContent = w;
      container.appendChild(item);
    });
  }

  async function doPreview() {
    const doc = $('#docInput').value.trim();
    if (!doc) {
      toast('先粘贴飞书文档链接', 'err');
      $('#docInput').focus();
      return;
    }
    const btn = $('#btnPreview');
    setBusy(btn, true, '读取中…');
    $('#previewBody').innerHTML = '<div class="skeleton"><i></i><i></i><i></i><i></i><i></i></div>';

    try {
      const data = await api('/api/preview', { doc });
      state.preview = data;
      renderPreview(data);
      showSettings(data);
      toast('已读取《' + data.doc_title + '》', 'ok');
    } catch (err) {
      $('#previewBody').innerHTML = '<div class="empty"><div class="empty-art">😵</div>'
        + '<h3>读取失败</h3><p>' + esc(err.message).replace(/\n/g, '<br>') + '</p></div>';
      toast(err.message.split('\n')[0], 'err');
    } finally {
      setBusy(btn, false, '读取并预览');
    }
  }

  function renderPreview(data) {
    const body = $('#previewBody');
    body.innerHTML = '';
    const warnBox = document.createElement('div');
    warnBox.className = 'warn-list';
    warnBox.style.marginBottom = '18px';
    renderWarnings(warnBox, data.warnings);
    if ((data.warnings || []).length) body.appendChild(warnBox);

    const article = document.createElement('article');
    article.className = 'md';
    article.innerHTML = renderMarkdown(data.preview);
    body.appendChild(article);

    const pill = $('#statPill');
    pill.hidden = false;
    pill.textContent = data.blocks + ' 块 · ' + data.chars + ' 字 · ' + data.images + ' 张图';
    $('#btnCopyMd').disabled = false;
    $('#btnDownload').disabled = false;
    body.scrollTop = 0;

    // 窄屏时预览在下方，读完后自动带过去
    if (window.innerWidth <= 980) {
      $('.preview-panel').scrollIntoView({ behavior: 'smooth', block: 'start' });
    }
  }

  function showSettings(data) {
    const panel = $('#settingsPanel');
    panel.hidden = false;
    $('#titleInput').value = data.title || '';

    const meta = data.meta || {};
    chipsCategories.set(meta.categories || (data.defaults && data.defaults.categories) || []);
    chipsTags.set(meta.tags || (data.defaults && data.defaults.tags) || []);

    if (data.existing) {
      $('#publishHint').textContent = '这篇文档之前发布过（文章 #' + data.existing.post_id + '），点发布会更新它。';
      $('#btnPublish .btn-label').textContent = '更新文章 #' + data.existing.post_id;
    } else {
      $('#publishHint').textContent = '默认存为草稿，确认排版后再公开发布。';
      $('#btnPublish .btn-label').textContent = '发布到博客园';
    }
  }

  /* ---------------- 发布 ---------------- */

  function updateProgress(job) {
    $('#progressPct').textContent = job.progress + '%';
    $('#progressFill').style.width = job.progress + '%';
    $('#progressTitle').textContent = job.status === 'error' ? '发布失败' : (job.status === 'done' ? '发布完成' : '正在发布…');
    const log = $('#progressLog');
    log.innerHTML = '';
    (job.logs || []).slice(-8).forEach((entry) => {
      const line = document.createElement('div');
      if (/失败|错误/.test(entry.m)) line.className = 'err';
      line.textContent = entry.m;
      log.appendChild(line);
    });
    log.scrollTop = log.scrollHeight;
  }

  function pollJob(jobId) {
    if (state.jobTimer) clearInterval(state.jobTimer);
    state.jobId = jobId;
    const tick = async () => {
      try {
        const job = await api('/api/job/' + jobId);
        updateProgress(job);
        if (job.status === 'done') {
          clearInterval(state.jobTimer);
          state.jobTimer = null;
          finishPublish(job);
        } else if (job.status === 'error') {
          clearInterval(state.jobTimer);
          state.jobTimer = null;
          failPublish(job.error || '发布失败');
        }
      } catch (err) {
        clearInterval(state.jobTimer);
        state.jobTimer = null;
        failPublish(err.message);
      }
    };
    state.jobTimer = setInterval(tick, 450);
    tick();
  }

  function finishPublish(job) {
    const result = job.result || {};
    setTimeout(() => { $('#progressCard').hidden = true; }, 900);

    const panel = $('#resultPanel');
    panel.hidden = false;
    panel.classList.remove('error');
    $('#resultIcon').textContent = '✓';
    $('#resultTitle').textContent = (result.action === 'updated' ? '已更新' : '已发布') + '《' + result.title + '》';
    $('#resultSub').textContent = '文章 ID ' + result.post_id + ' · '
      + (result.draft ? '草稿（非公开）' : '已公开');

    const actions = $('#resultActions');
    actions.innerHTML = '';
    const open = document.createElement('a');
    open.className = 'btn';
    open.href = result.url;
    open.target = '_blank';
    open.rel = 'noopener';
    open.textContent = '打开文章';
    open.style.textDecoration = 'none';
    actions.appendChild(open);

    const copy = document.createElement('button');
    copy.className = 'ghost-btn';
    copy.textContent = '复制链接';
    copy.addEventListener('click', async () => {
      const ok = await copyText(result.url);
      toast(ok ? '链接已复制' : '复制失败', ok ? 'ok' : 'err');
    });
    actions.appendChild(copy);

    if (result.draft) {
      const pub = document.createElement('button');
      pub.className = 'ghost-btn primary-ghost';
      pub.textContent = '改成公开发布';
      pub.addEventListener('click', () => {
        $('#optPublic').checked = true;
        doPublish();
      });
      actions.appendChild(pub);
    }

    renderWarnings($('#resultWarnings'), result.warnings);
    panel.scrollIntoView({ behavior: 'smooth', block: 'nearest' });
    toast(result.draft ? '已存为草稿' : '已公开发布', 'ok');
    refreshHistory();
  }

  function failPublish(message) {
    $('#progressTitle').textContent = '发布失败';
    $('#progressPct').textContent = '—';
    const log = $('#progressLog');
    const line = document.createElement('div');
    line.className = 'err';
    line.textContent = message;
    log.appendChild(line);

    const panel = $('#resultPanel');
    panel.hidden = false;
    panel.classList.add('error');
    $('#resultIcon').textContent = '!';
    $('#resultTitle').textContent = '发布失败';
    $('#resultSub').textContent = message.split('\n')[0];
    $('#resultActions').innerHTML = '';
    renderWarnings($('#resultWarnings'), message.split('\n').slice(1));
    toast('发布失败：' + message.split('\n')[0], 'err');
  }

  async function doPublish() {
    if (!state.preview) {
      toast('请先读取并预览文档', 'err');
      return;
    }
    const isPublic = $('#optPublic').checked;
    if (isPublic && !window.confirm('确定要直接公开发布吗？\n公开文章可能进入博客园人工审核。')) {
      return;
    }
    const payload = {
      doc: $('#docInput').value.trim(),
      title: $('#titleInput').value.trim(),
      categories: chipsCategories.get(),
      tags: chipsTags.get(),
      summary: $('#summaryInput').value.trim(),
      publish: isPublic,
      forceNew: $('#optForceNew').checked,
      aiDeclaration: $('#optAi').checked,
      sourceLink: $('#optSource').checked,
      uploadImages: !$('#optNoImages').checked,
    };

    const btn = $('#btnPublish');
    setBusy(btn, true, '发布中…');
    $('#progressCard').hidden = false;
    $('#resultPanel').hidden = true;
    $('#progressLog').innerHTML = '';
    $('#progressFill').style.width = '2%';
    $('#progressPct').textContent = '0%';
    $('#progressTitle').textContent = '正在发布…';

    try {
      const data = await api('/api/publish', payload);
      pollJob(data.job);
    } catch (err) {
      $('#progressCard').hidden = true;
      failPublish(err.message);
    } finally {
      setBusy(btn, false, null);
    }
  }

  /* ---------------- 历史 ---------------- */

  async function refreshHistory() {
    try {
      const data = await api('/api/history');
      renderHistory(data.items || []);
    } catch (e) { /* 抽屉没打开时忽略 */ }
  }

  function renderHistory(items) {
    const list = $('#historyList');
    list.innerHTML = '';
    if (!items.length) {
      list.innerHTML = '<div class="empty" style="padding:30px 0"><div class="empty-art">📭</div>'
        + '<p>还没有发布记录<br>发布第一篇之后会出现在这里</p></div>';
      return;
    }
    items.forEach((item) => {
      const el = document.createElement('div');
      el.className = 'history-item';
      el.innerHTML = '<div class="history-top"><h4></h4></div>'
        + '<div class="history-meta"><span class="badge"></span><span class="id"></span><span class="date"></span></div>'
        + '<div class="history-actions"></div>';
      el.querySelector('h4').textContent = item.title || '（无标题）';
      const badge = el.querySelector('.badge');
      badge.textContent = item.draft ? '草稿' : '公开';
      if (!item.draft) badge.classList.add('pub');
      el.querySelector('.id').textContent = '#' + item.post_id;
      el.querySelector('.date').textContent = (item.updated_at || '').replace('T', ' ').slice(0, 16);

      const actions = el.querySelector('.history-actions');
      const open = document.createElement('a');
      open.className = 'ghost-btn sm';
      open.href = item.url || '#';
      open.target = '_blank';
      open.rel = 'noopener';
      open.textContent = '打开';
      open.style.textDecoration = 'none';
      actions.appendChild(open);

      const fill = document.createElement('button');
      fill.className = 'ghost-btn sm';
      fill.textContent = '填入链接';
      fill.addEventListener('click', () => {
        $('#docInput').value = item.source || '';
        closeDrawer();
        toast('已填入，点「读取并预览」');
      });
      actions.appendChild(fill);

      const del = document.createElement('button');
      del.className = 'ghost-btn sm';
      del.textContent = '删除记录';
      del.addEventListener('click', async () => {
        if (!window.confirm('只删除本地记录，不会删除博客文章。继续？')) return;
        try {
          await api('/api/history/delete', { doc_id: item.doc_id });
          toast('记录已删除');
          refreshHistory();
        } catch (err) {
          toast(err.message, 'err');
        }
      });
      actions.appendChild(del);

      list.appendChild(el);
    });
  }

  function openDrawer() {
    $('#historyDrawer').classList.add('open');
    $('#historyDrawer').setAttribute('aria-hidden', 'false');
    $('#scrim').hidden = false;
    refreshHistory();
  }
  function closeDrawer() {
    $('#historyDrawer').classList.remove('open');
    $('#historyDrawer').setAttribute('aria-hidden', 'true');
    if (!$('#settingsModal').classList.contains('open')) $('#scrim').hidden = true;
  }

  /* ---------------- 设置 ---------------- */

  function openSettings() {
    $('#settingsModal').classList.add('open');
    $('#settingsModal').setAttribute('aria-hidden', 'false');
    $('#scrim').hidden = false;
    $('#checkResult').hidden = true;
  }
  function closeSettings() {
    $('#settingsModal').classList.remove('open');
    $('#settingsModal').setAttribute('aria-hidden', 'true');
    if (!$('#historyDrawer').classList.contains('open')) $('#scrim').hidden = true;
  }

  async function saveSettings() {
    const btn = $('#btnSaveSettings');
    btn.disabled = true;
    try {
      await api('/api/config', {
        feishu: {
          app_id: $('#setAppId').value.trim(),
          app_secret: $('#setAppSecret').value.trim(),
          user_token: $('#setUserToken').value.trim(),
        },
        cnblogs: {
          username: $('#setUsername').value.trim(),
          blog: $('#setBlog').value.trim(),
          token: $('#setToken').value.trim(),
          categories: $('#setCategories').value.trim(),
          tags: $('#setTags').value.trim(),
        },
      });
      await refreshConfig();
      toast('设置已保存', 'ok');
    } catch (err) {
      toast(err.message.split('\n')[0], 'err');
    } finally {
      btn.disabled = false;
    }
  }

  async function testConnection() {
    const box = $('#checkResult');
    const btn = $('#btnTestConn');
    box.hidden = false;
    box.innerHTML = '<div class="check-line">正在测试…</div>';
    btn.disabled = true;
    try {
      const result = await api('/api/check', { doc: $('#docInput').value.trim() || null });
      box.innerHTML = '';
      const add = (label, item) => {
        const line = document.createElement('div');
        line.className = 'check-line ' + (item.ok ? 'ok' : 'bad');
        line.textContent = (item.ok ? '✓ ' : '✗ ') + label;
        if (!item.ok && item.error) {
          const span = document.createElement('span');
          span.textContent = item.error;
          line.appendChild(span);
        } else if (item.ok) {
          const span = document.createElement('span');
          let extra = '';
          if (item.auth) extra = '凭证有效（' + item.auth + '）';
          if (item.blogs && item.blogs.length) extra = '可用博客：' + item.blogs.join('、');
          if (item.document) extra = '文档可读：《' + item.document.title + '》，' + item.document.blocks + ' 个块';
          span.textContent = extra;
          line.appendChild(span);
        }
        box.appendChild(line);
      };
      add('飞书', result.feishu || {});
      add('博客园', result.cnblogs || {});
      await refreshConfig();
    } catch (err) {
      box.innerHTML = '<div class="check-line bad">' + esc(err.message) + '</div>';
    } finally {
      btn.disabled = false;
    }
  }

  /* ---------------- 主题 ---------------- */

  function applyTheme(theme) {
    document.documentElement.setAttribute('data-theme', theme);
    localStorage.setItem('f2c-theme', theme);
    $('#btnTheme').textContent = theme === 'dark' ? '☀' : '◐';
  }

  /* ---------------- 事件绑定 ---------------- */

  function bind() {
    $('#btnPreview').addEventListener('click', doPreview);
    $('#docInput').addEventListener('keydown', (e) => {
      if (e.key === 'Enter' && (e.ctrlKey || e.metaKey || !e.shiftKey)) {
        e.preventDefault();
        doPreview();
      }
    });
    $('#btnPaste').addEventListener('click', async () => {
      try {
        const text = await navigator.clipboard.readText();
        if (text) {
          $('#docInput').value = text.trim();
          toast('已粘贴');
        }
      } catch (e) {
        toast('浏览器不允许读取剪贴板，请手动粘贴', 'err');
        $('#docInput').focus();
      }
    });

    $('#btnPublish').addEventListener('click', doPublish);

    $('#btnCopyMd').addEventListener('click', async () => {
      if (!state.preview) return;
      const text = '# ' + (state.preview.title || '未命名') + '\n\n' + state.preview.markdown;
      const ok = await copyText(text);
      toast(ok ? 'Markdown 已复制' : '复制失败', ok ? 'ok' : 'err');
    });

    $('#btnDownload').addEventListener('click', () => {
      if (!state.preview) return;
      const name = (state.preview.title || 'document').replace(/[\\/:*?"<>|]/g, '_');
      const text = '# ' + (state.preview.title || '未命名') + '\n\n' + state.preview.markdown;
      const blob = new Blob([text], { type: 'text/markdown;charset=utf-8' });
      const a = document.createElement('a');
      a.href = URL.createObjectURL(blob);
      a.download = name + '.md';
      a.click();
      setTimeout(() => URL.revokeObjectURL(a.href), 4000);
      toast('已下载 ' + name + '.md');
    });

    // 代码块复制（事件委托）
    $('#previewBody').addEventListener('click', async (e) => {
      const btn = e.target.closest('[data-copy]');
      if (!btn) return;
      const code = btn.closest('.code-block').querySelector('code');
      const ok = await copyText(code ? code.textContent : '');
      btn.textContent = ok ? '已复制' : '失败';
      setTimeout(() => { btn.textContent = '复制'; }, 1400);
    });

    $('#btnTheme').addEventListener('click', () => {
      const next = document.documentElement.getAttribute('data-theme') === 'dark' ? 'light' : 'dark';
      applyTheme(next);
    });

    $('#btnHistory').addEventListener('click', openDrawer);
    $('#btnCloseHistory').addEventListener('click', closeDrawer);
    $('#btnSettings').addEventListener('click', openSettings);
    $('#btnCloseSettings').addEventListener('click', closeSettings);
    $('#btnSaveSettings').addEventListener('click', saveSettings);
    $('#btnTestConn').addEventListener('click', testConnection);

    $('#scrim').addEventListener('click', () => { closeDrawer(); closeSettings(); });
    document.addEventListener('keydown', (e) => {
      if (e.key === 'Escape') { closeDrawer(); closeSettings(); }
    });

    $('#btnCopyBookmarklet').addEventListener('click', async () => {
      const ok = await copyText($('#bookmarkletUrl').value);
      toast(ok ? '已复制书签代码' : '复制失败', ok ? 'ok' : 'err');
    });

    chipsCategories = Chips($('#chipsCategories'), [], () => {});
    chipsTags = Chips($('#chipsTags'), [], () => {});
  }

  /* ---------------- 启动 ---------------- */

  async function boot() {
    const params = new URLSearchParams(location.search);
    const themed = params.get('theme');
    applyTheme(themed === 'dark' || themed === 'light'
      ? themed
      : (localStorage.getItem('f2c-theme')
        || (window.matchMedia && window.matchMedia('(prefers-color-scheme: dark)').matches ? 'dark' : 'light')));

    try {
      const session = await api('/api/session');
      state.token = session.token;
    } catch (err) {
      document.body.innerHTML = '<div class="empty" style="padding-top:20vh">'
        + '<div class="empty-art">🔌</div><h3>连不上本地服务</h3>'
        + '<p>' + esc(err.message) + '</p></div>';
      return;
    }

    bind();
    await refreshConfig();

    $('#bookmarkletUrl').value =
      "javascript:(function(){window.open('" + location.origin + "/?doc='+encodeURIComponent(location.href),'_blank')})()";

    const doc = new URLSearchParams(location.search).get('doc');
    if (doc) {
      $('#docInput').value = doc;
      doPreview();
    }

    const panel = params.get('panel');
    if (panel === 'settings') openSettings();
    if (panel === 'history') openDrawer();

    // 布局自检：?debug=1 时把视口尺寸和越界元素写进页面，便于排查响应式问题
    if (params.get('debug')) {
      setTimeout(() => {
        const vw = window.innerWidth;
        const wide = Array.from(document.querySelectorAll('body *'))
          .filter((el) => el.getBoundingClientRect().right > vw + 1)
          .slice(0, 8)
          .map((el) => el.tagName.toLowerCase() + '.' + (el.className || '')
            + ' →' + Math.round(el.getBoundingClientRect().right));
        const pre = document.createElement('pre');
        pre.id = 'debugBox';
        pre.textContent = 'innerWidth=' + vw + ' scrollWidth=' + document.documentElement.scrollWidth
          + ' dpr=' + window.devicePixelRatio + '\noverflow: ' + (wide.join(' | ') || 'none');
        document.body.appendChild(pre);
      }, 1200);
    }

    if (!state.config.feishu.ready || !state.config.cnblogs.ready) {
      setTimeout(() => {
        toast('还没配置凭据，先点右上角「设置」', 'err');
      }, 700);
    }
  }

  boot();
})();
