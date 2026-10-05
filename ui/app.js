/* TensorFold Manager v2 前端：严格以 prototypes/tfm2.html 为唯一基准。
   所有渲染接真实数据（window.bridge → backend/api.py），样式零重新发明。 */
'use strict';

const $ = (id) => document.getElementById(id);
const esc = (s) => String(s == null ? '' : s)
  .replace(/&/g, '&amp;').replace(/</g, '&lt;').replace(/>/g, '&gt;').replace(/"/g, '&quot;');

const ST = {
  family: [], inst: [], cache: [], pulls: {}, appset: {}, upd: {},
  chats: [], cur: null, streaming: false, settings: {},
};

/* ---------- 桥 ---------- */
async function call(method, args) {
  if (!window.bridge) throw new Error('bridge 不可用');
  return window.bridge.call(method, args || {});
}

function toast(msg, ms) {
  let t = $('toast');
  if (!t) { t = document.createElement('div'); t.id = 'toast'; document.body.appendChild(t); }
  t.textContent = msg;
  t.classList.add('show');
  clearTimeout(t._h);
  t._h = setTimeout(() => t.classList.remove('show'), ms || 3500);
}

/* ---------- 主题 ---------- */
function applyTheme(mode) {
  const dark = mode === 'dark';
  document.documentElement.setAttribute('data-theme', dark ? 'dark' : 'light');
  const b = $('win-theme'); if (b) b.textContent = dark ? '☀️' : '🌙';
}
function toggleTheme() {
  const dark = document.documentElement.getAttribute('data-theme') === 'dark';
  applyTheme(dark ? 'light' : 'dark');
  call('app_settings_save', { theme: dark ? 'light' : 'dark' }).catch(() => {});
}

/* ---------- 轮询 ---------- */
async function refresh() {
  try {
    const ov = await call('overview', {});
    ST.inst = ov.instances || [];
    ST.proxyPort = ov.proxy_port || 0;
    renderTopbar(ov);
    renderSide(ov);
    if ($('page-models').classList.contains('on')) await renderModelsPage();
    if ($('page-metrics').classList.contains('on')) renderMetrics(ov);
    ST.upd = await call('update_status', {}).catch(() => ST.upd);
    renderUpdate();
  } catch (e) { /* 壳未就绪时静默 */ }
}

function renderTopbar(ov) {
  const ready = ST.inst.filter(i => i.state === 'ready');
  const starting = ST.inst.filter(i => i.state === 'starting');
  const dot = $('win-dot'), st = $('win-status'), pw = $('win-power');
  if (ready.length) {
    dot.className = 'dot on';
    st.textContent = `— 引擎运行中 · :${ready[0].port}${ready.length > 1 ? ` · ${ready.length} 实例` : ''}`;
    pw.textContent = '■ 停止引擎'; pw.className = 'tbtn stop';
  } else if (starting.length) {
    dot.className = 'dot on';
    st.textContent = `— 启动中… ${starting[0].name}`;
    pw.textContent = '■ 停止引擎'; pw.className = 'tbtn stop';
  } else {
    dot.className = 'dot off';
    st.textContent = '— 引擎未运行';
    pw.textContent = '▶ 启动引擎'; pw.className = 'tbtn run';
  }
  // 顶栏版本 + 绿点悬停提示（原型 .ver 组件）
  const ver = $('win-ver'), vtip = $('win-vtip');
  const eng = (ST.upd && ST.upd.engine) || {}, app = (ST.upd && ST.upd.app) || {};
  ver.childNodes[0].nodeValue = 'v' + (ST.settings.app_version || '2.0.0');
  vtip.textContent = eng.available ? `引擎有新版本 v${eng.latest}，设置页一键升级`
    : app.available ? `App 有新版本 v${app.latest}`
    : `引擎 ${ST.settings.version || '—'} · 已是最新`;
  ver.classList.toggle('new', !!(eng.available || app.available));
}

function renderSide(ov) {
  const ready = ST.inst.filter(i => i.state === 'ready');
  const dot = $('side-dot'), txt = $('side-status');
  if (ready.length) {
    dot.className = 'dot on';
    const i = ready[0];
    const ctx = i.params && i.params.context ? ` · ${(i.params.context / 1024) | 0}k` : '';
    txt.textContent = `${i.name} :${i.port}${ctx}${ready.length > 1 ? ` +${ready.length - 1}` : ''}`;
  } else {
    dot.className = 'dot off';
    txt.textContent = '引擎未运行';
  }
}

function renderBadge() {
  const n = Object.keys(ST.pulls || {}).length;
  const b = $('nav-dl-badge');
  b.style.display = n ? 'inline-flex' : 'none';
  b.textContent = n;
}

/* ---------- 模型页（第一页） ---------- */
async function renderModelsPage() {
  if (!ST.family.length) ST.family = await call('families', {}).catch(() => []);
  try { ST.cache = await call('models_installed', {}); } catch (e) {}
  try { ST.pulls = await call('pull_status', {}); } catch (e) {}
  renderCards();
  renderCacheList();
  renderBadge();
}

const instOf = (id) => ST.inst.find(i => i.model === id);
const cacheOf = (id) => ST.cache.find(m => m.id === id);

function renderCards() {
  $('mcards').innerHTML = ST.family.map(f => {
    const inst = instOf(f.id), cached = cacheOf(f.id), pull = (ST.pulls || {})[f.id];
    const badges = [];
    if (inst && inst.state === 'ready') badges.push('<span class="badge run">● 运行中</span>');
    else if (inst && inst.state === 'starting') badges.push('<span class="badge own">◌ 启动中</span>');
    else if (inst && inst.state === 'error') badges.push('<span class="badge" style="background:var(--danger-bg);color:var(--danger)">✕ 异常</span>');
    if (pull) badges.push('<span class="badge own" style="color:var(--dl-ink)">下载中</span>');
    else if (cached) badges.push('<span class="badge own">已缓存</span>');

    let sz, prog = '';
    if (pull) {
      prog = '<div class="prog"><i style="width:34%"></i></div>';
      sz = '下载中 · tensorfold pull';
    } else if (cached) sz = `${cached.size_gb} GB`;
    else sz = f.size_gb ? `未缓存 · 下载约 ${f.size_gb} GB` : '未缓存';

    const running = !!(inst && inst.state !== 'idle');
    const loadBtn = running
      ? '<button class="sbtn" disabled>加载</button>'
      : (cached
          ? `<button class="sbtn" onclick="loadModel('${esc(f.id)}')">加载</button>`
          : `<button class="sbtn pri" onclick="loadModel('${esc(f.id)}')">↓ 下载</button>`);
    const delBtn = (cached && !running)
      ? `<button class="sbtn del" onclick="delModel('${esc(f.id)}')">删除</button>`
      : `<button class="sbtn del" disabled${running ? ' title="运行中不可删"' : ''}>删除</button>`;
    return `<div class="mcard${inst && inst.state === 'ready' ? ' active' : ''}">
      <div class="mt"><b>${esc(f.name)}</b>${badges.join('')}</div>
      <div class="rid">${esc(f.id)}</div>
      <div class="desc">${esc(f.note || '')}</div>
      ${prog}
      <div class="row"><span class="sz">${esc(sz)}</span>${loadBtn}<button class="sbtn" onclick="openSettings('${esc(f.id)}')">设置</button>${delBtn}</div>
    </div>`;
  }).join('');
}

window.loadModel = async function (id) {
  const cached = cacheOf(id);
  if (!cached) {
    toast(`开始下载 ${id.split('/').pop()}（后台进行，可继续操作）`);
    const r = await call('model_pull', { repo_id: id }).catch(e => ({ error: String(e) }));
    if (r && r.error) toast('下载失败: ' + r.error);
  } else {
    toast(`正在加载 ${id.split('/').pop()} …（约 30s）`);
    const r = await call('engine_start', { model: id }).catch(e => ({ error: String(e) }));
    if (r && r.error) toast('加载失败: ' + r.error);
  }
  setTimeout(refresh, 800);
  setTimeout(refresh, 5000);
};

window.delModel = async function (id) {
  if (!confirm(`删除缓存 ${id} ？\n（重新加载需重新下载）`)) return;
  const r = await call('model_delete', { repo_id: id }).catch(e => ({ error: String(e) }));
  toast(r && r.ok ? '已删除' : '删除失败: ' + (r && r.error));
  refresh();
};

function renderCacheList() {
  const box = $('cache-list');
  if (!ST.cache.length) { box.innerHTML = '<div class="empty" style="padding:13px 16px;color:var(--ink4)">缓存为空，点上方「↓ 下载」拉取官方模型</div>'; return; }
  box.innerHTML = ST.cache.map(m => {
    const inst = instOf(m.id), running = inst && inst.alive;
    return `<div class="pitem"><span class="dot ${running ? 'on' : 'off'}"></span><span class="mono">${esc(m.id)}</span><span class="right">${m.size_gb} GB${running ? ' · 运行中' : ''}<button class="sbtn del" ${running ? 'disabled title="运行中不可删"' : `onclick="delModel('${esc(m.id)}')"`}>删除</button></span></div>`;
  }).join('');
}

/* ---------- 对话页 ---------- */
async function loadChats() {
  ST.chats = await call('chat_list', {}).catch(() => []);
  const box = $('convs');
  box.innerHTML = ST.chats.map(c =>
    `<div class="conv${ST.cur && ST.cur.id === c.id ? ' on' : ''}" data-id="${esc(c.id)}">${esc(c.title)}<div class="meta">${fmtTime(c.updated)}</div></div>`).join('')
    || '<div class="conv" style="cursor:default;color:var(--ink4)">暂无会话</div>';
  box.querySelectorAll('.conv[data-id]').forEach(el =>
    el.addEventListener('click', () => openChat(el.dataset.id)));
}

function fmtTime(ts) {
  if (!ts) return '';
  const d = new Date(ts * 1000), now = new Date();
  const hm = `${String(d.getHours()).padStart(2, '0')}:${String(d.getMinutes()).padStart(2, '0')}`;
  if (d.toDateString() === now.toDateString()) return `今天 ${hm}`;
  const y = new Date(now); y.setDate(y.getDate() - 1);
  if (d.toDateString() === y.toDateString()) return `昨天 ${hm}`;
  return `${d.getMonth() + 1}月${d.getDate()}日`;
}

async function newChat() {
  const model = $('chat-model').value || '';
  ST.cur = await call('chat_create', { chat: { title: '新对话', model } });
  renderChatBody(); loadChats();
}

async function openChat(id) {
  ST.cur = await call('chat_get', { chat_id: id });
  if (ST.cur && ST.cur.model) $('chat-model').value = ST.cur.model;
  renderChatBody(); loadChats();
}

function md(text) {
  try { return DOMPurify.sanitize(marked.parse(text || '')); }
  catch (e) { return esc(text).replace(/\n/g, '<br>'); }
}

function msgHtml(m) {
  const who = m.role === 'user' ? '你' : (ST.cur && ST.cur.model ? ST.cur.model.split('/').pop() : '模型');
  const body = m.role === 'user'
    ? `<div class="bub">${esc(m.content).replace(/\n/g, '<br>')}</div>`
    : `<div class="bub">${md(m.content)}</div>`;
  const stats = m.stats ? `<div class="tps">${m.stats.tps ? `<span>${m.stats.tps} tok/s</span>` : ''}${m.stats.ms ? `<span>首 token ${m.stats.ms}ms</span>` : ''}</div>` : '';
  return `<div class="msg ${m.role === 'user' ? 'user' : 'ai'}"><span class="who">${esc(who)}</span>${body}${stats}</div>`;
}

function renderChatBody() {
  const body = $('chat-body');
  body.innerHTML = (ST.cur && ST.cur.messages ? ST.cur.messages : []).map(msgHtml).join('')
    || '<div style="color:var(--ink4);align-self:center;margin-top:40px;font-size:13px">选一个已加载模型，开聊</div>';
  body.scrollTop = body.scrollHeight;
  renderChatTop();
}

function renderChatTop() {
  const sel = $('chat-model');
  const ready = ST.inst.filter(i => i.state === 'ready');
  const cur = sel.value;
  sel.innerHTML = ready.length
    ? ready.map(i => `<option value="${esc(i.model)}">${esc(i.model.split('/').pop())}</option>`).join('')
    : '<option value="">（无已加载模型，去模型页点「加载」）</option>';
  if (ready.some(i => i.model === cur)) sel.value = cur;
  else if (ST.cur && ST.cur.model && ready.some(i => i.model === ST.cur.model)) sel.value = ST.cur.model;
  const inst = ready.find(i => i.model === sel.value);
  $('chat-ctx').textContent = inst && inst.params && inst.params.context ? `ctx ${(inst.params.context / 1024) | 0}k` : 'ctx —';
}

async function send() {
  const ta = $('chat-text');
  const text = ta.value.trim();
  const model = $('chat-model').value;
  if (!text || ST.streaming) return;
  if (!model) { toast('请先在模型页加载一个模型'); return; }
  ta.value = '';
  if (!ST.cur) ST.cur = await call('chat_create', { chat: { title: text.slice(0, 24), model } });
  if (ST.cur.title === '新对话') ST.cur.title = text.slice(0, 24);
  ST.cur.model = model;
  ST.cur.messages.push({ role: 'user', content: text });
  renderChatBody(); loadChats();
  await call('chat_save', { chat: ST.cur }).catch(() => {});

  ST.streaming = true; $('btn-send').disabled = true;
  const ai = { role: 'assistant', content: '' };
  ST.cur.messages.push(ai);
  renderChatBody();
  const t0 = performance.now();
  let firstMs = null;
  try {
    const resp = await fetch(`http://127.0.0.1:${ST.proxyPort}/chat`, {
      method: 'POST', headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ model, stream: true, messages: ST.cur.messages.slice(0, -1) })
    });
    if (!resp.ok) throw new Error(`HTTP ${resp.status} ${(await resp.text().catch(() => '')).slice(0, 120)}`);
    const reader = resp.body.getReader();
    const dec = new TextDecoder();
    let buf = '';
    const body = $('chat-body');
    const el = body.lastElementChild.querySelector('.bub');
    while (true) {
      const { done, value } = await reader.read();
      if (done) break;
      buf += dec.decode(value, { stream: true });
      let idx;
      while ((idx = buf.indexOf('\n\n')) >= 0) {
        const part = buf.slice(0, idx); buf = buf.slice(idx + 2);
        for (const line of part.split('\n')) {
          if (!line.startsWith('data:')) continue;
          const s = line.slice(5).trim();
          if (s === '[DONE]') continue;
          try {
            const d = JSON.parse(s);
            const piece = d.choices && d.choices[0] && d.choices[0].delta && d.choices[0].delta.content;
            if (piece) {
              if (firstMs === null) firstMs = Math.round(performance.now() - t0);
              ai.content += piece;
              el.innerHTML = md(ai.content);
              body.scrollTop = body.scrollHeight;
            }
          } catch (e) {}
        }
      }
    }
    const secs = (performance.now() - t0) / 1000;
    ai.stats = { ms: firstMs, tps: secs > 0 ? Math.round(ai.content.length / secs * 4 / 4) : null };
  } catch (e) {
    ai.content += (ai.content ? '\n\n' : '') + `⚠️ ${e}`;
  } finally {
    ST.streaming = false; $('btn-send').disabled = false;
  }
  renderChatBody();
  await call('chat_save', { chat: ST.cur }).catch(() => {});
  loadChats();
}

/* ---------- 监控页 ---------- */
function renderMetrics(ov) {
  const L = ov.metrics_latest || {}, per = ov.per || {}, S = ov.series || {};
  $('st-tps').innerHTML = (L.tps != null ? fmtNum(L.tps) : '—') + '<small>tok/s</small>';
  $('st-mem').innerHTML = (L.footprint_gb != null ? L.footprint_gb : '—') + (L.footprint_gb != null ? '<small>GB</small>' : '');
  $('st-free').innerHTML = (ov.mem_free != null ? ov.mem_free : '—') + (ov.mem_free != null ? `<small>GB / ${ov.mem_total}GB</small>` : '');
  $('st-kv').innerHTML = (L.kv != null ? L.kv : '—') + '<small>%</small>';
  $('st-req').innerHTML = (L.running != null ? L.running : '—') + '<small>活跃</small>';
  $('st-req-sub').textContent = `${L.running || 0} 活跃 · ${L.waiting || 0} 排队`;
  const ratios = Object.values(per).map(p => p.accepted_ratio).filter(v => v != null);
  $('st-mtp').innerHTML = ratios.length ? (Math.max(...ratios) * 100).toFixed(1) + '<small>%</small>' : '—';
  $('st-inst').textContent = ST.inst.filter(i => i.state === 'ready').length;

  bars('bars-tps', (S.tps || {}).values, v => v);
  bars('bars-mem', (S.footprint_gb || {}).values, v => v);
  bars('bars-free', (S.mem_free || {}).values, v => v, true);

  const vals = ((S.tps || {}).values || []).slice(-60);
  const svg = $('chart-tps');
  if (vals.length >= 2) {
    const max = Math.max(...vals, 1);
    const pts = vals.map((v, i) => `${(i / (vals.length - 1)) * 520},${110 - (v / max) * 100}`).join(' ');
    svg.innerHTML = `<g stroke="var(--line)" stroke-width="1"><line x1="0" y1="27" x2="520" y2="27"/><line x1="0" y1="55" x2="520" y2="55"/><line x1="0" y1="82" x2="520" y2="82"/></g><polyline fill="none" stroke="var(--ok)" stroke-width="2" points="${pts}"/>`;
  } else {
    svg.innerHTML = '<text x="260" y="55" fill="var(--ink4)" font-size="11" text-anchor="middle">暂无吞吐数据</text>';
  }

  $('inst-list').innerHTML = ST.inst.length ? ST.inst.map(i =>
    `<div class="pitem"><span class="dot ${i.state === 'ready' ? 'on' : 'off'}"></span><span class="mono">${esc(i.model)}</span><span class="right">:${i.port} · ${i.state}${i.uptime ? ' · ' + fmtUp(i.uptime) : ''} · ${i.params && i.params.context ? (i.params.context / 1024) + 'k' : '—'}<button class="sbtn del" ${i.state === 'idle' ? 'disabled' : `onclick="stopModel('${esc(i.model)}')"`}>停止</button></span></div>`).join('')
    : '<div class="empty" style="padding:13px 16px;color:var(--ink4)">没有引擎实例，去模型页点「加载」</div>';
}

const fmtNum = (v) => v >= 1000 ? (v / 1000).toFixed(1) + 'k' : String(Math.round(v * 10) / 10);
function fmtUp(s) { s = Math.round(s); const h = (s / 3600) | 0, m = ((s % 3600) / 60) | 0; return h ? `${h}h ${m}m` : `${m}m ${s % 60}s`; }

function bars(id, vals, get, invert) {
  const box = $(id);
  const v = (vals || []).slice(-10);
  if (!v.length) { box.innerHTML = '<i style="height:4%"></i>'.repeat(10); return; }
  const max = Math.max(...v.map(get), 1);
  box.innerHTML = v.map(x => {
    const p = (get(x) / max) * 100;
    const hot = invert ? '' : (p > 90 ? ' class="max"' : p > 75 ? ' class="hot"' : '');
    return `<i${hot} style="height:${Math.max(p, 3)}%"></i>`;
  }).join('');
}

window.stopModel = async function (model) {
  const r = await call('engine_stop', { model }).catch(e => ({ error: String(e) }));
  if (r && r.error) toast(r.error);
  refresh();
};

window.stopAll = async function () {
  const running = ST.inst.some(i => i.state === 'ready' || i.state === 'starting');
  if (running) {
    const r = await call('engine_stop', {}).catch(e => ({ error: String(e) }));
    toast(r && r.error ? r.error : '已停止全部引擎');
  } else {
    const def = (ST.appset && ST.appset.default_model) || (ST.cache[0] && ST.cache[0].id);
    if (!def) { toast('没有已缓存模型，去模型页下载一个'); switchPage('models'); return; }
    toast(`正在加载 ${def.split('/').pop()} …`);
    const r = await call('engine_start', { model: def }).catch(e => ({ error: String(e) }));
    if (r && r.error) toast('加载失败: ' + r.error);
  }
  setTimeout(refresh, 800); setTimeout(refresh, 5000);
};

/* ---------- 设置页 ---------- */
async function loadSettings() {
  try { ST.appset = await call('app_settings_get', {}); } catch (e) { ST.appset = {}; }
  $('set-ctx').value = ST.appset.default_context;
  $('set-parallel').value = ST.appset.parallel;
  $('set-pcache').value = ST.appset.prompt_cache_gib;
  $('set-autostart').classList.toggle('on', !!ST.appset.autostart_engine);
  $('set-updcheck').classList.toggle('on', ST.appset.auto_update_check !== false);
  $('set-menubar').classList.toggle('on', ST.appset.menubar !== false);
  $('set-close2mb').classList.toggle('on', ST.appset.close_to_menubar !== false);
  ST.settings = await call('settings', {}).catch(() => ST.settings || {});
  const last = ST.upd && ST.upd.checked_at ? ' · 上次检查 ' + fmtTime(ST.upd.checked_at) : '';
  $('ver-sub').textContent = `App v${ST.settings.app_version || '—'} · 引擎 ${ST.settings.version || '未安装'}${last}`;
  $('btn-copyapi').textContent = `http://127.0.0.1:${ST.settings.proxy_port || 8080}/v1 ⧉`;
  renderUpdate();
}

function renderUpdate() {
  const u = ST.upd || {}, eng = u.engine || {}, app = u.app || {};
  const row = $('upd-row');
  const avail = eng.available || app.available;
  row.style.display = avail ? 'flex' : 'none';
  if (!avail) return;
  const parts = [];
  if (eng.available) parts.push(`引擎 v${eng.latest}`);
  if (app.available) parts.push(`App v${app.latest}${app.prerelease ? '（预发布）' : ''}`);
  row.querySelector('.sl span').textContent = parts.join(' · ') + ' · 点击右侧一键升级';
}

async function doUpdateCheck() {
  toast('正在检查 GitHub 更新 …');
  ST.upd = await call('update_check', {}).catch(e => ({ error: String(e) }));
  if (ST.upd && ST.upd.error) toast('检查失败: ' + ST.upd.error); else toast('检查完成');
  ST.settings = await call('settings', {}).catch(() => ST.settings);
  loadSettings();
  renderTopbar(await call('overview', {}).catch(() => ({ instances: [] })));
}

async function doUpdateApply() {
  const eng = (ST.upd.engine || {});
  if (eng.available) {
    if (!confirm(`升级引擎到 v${eng.latest}？\n将从 GitHub 拉取覆盖安装，运行中实例需重启生效。`)) return;
    toast('正在从 GitHub 拉取安装（可能需要 1-2 分钟）…');
    const r = await call('update_apply_engine', {}).catch(e => ({ error: String(e) }));
    toast(r && r.ok ? `已升级到 ${r.version}，重启实例后生效` : '升级失败: ' + (r && r.error));
  } else if ((ST.upd.app || {}).url) {
    call('update_open_app', {}).catch(() => {});
    toast('已在浏览器打开 App 下载页');
  }
}

/* ---------- 模型设置弹窗 ---------- */
async function openSettings(model) {
  ST.msModel = model;
  $('ms-title').textContent = '模型设置 — ' + model.split('/').pop();
  let p = {};
  try { p = await call('model_settings_get', { model }); } catch (e) {}
  $('ms-context').value = p.context || 32768;
  $('ms-maxtok').value = p.max_tokens || 4096;
  $('ms-temp').value = p.temperature != null ? p.temperature : '';
  $('ms-topp').value = p.top_p != null ? p.top_p : '';
  $('ms-thinking').classList.toggle('on', !!p.thinking);
  $('ms-effort').value = p.reasoning_effort || '';
  $('ms-parallel').value = p.parallel != null ? p.parallel : '';
  $('ms-port').value = p.port != null ? p.port : '';
  $('ms-mtpd').value = p.mtp_drafts != null ? p.mtp_drafts : '';
  $('ms-mtpc').value = p.mtp_confidence != null ? p.mtp_confidence : '';
  $('ms-kvdt').value = p.kv_dtype || '';
  $('ms-pcache').value = p.prompt_cache_gib != null ? p.prompt_cache_gib : '';
  $('ms-vision').classList.toggle('on', !!p.vision);
  $('ms-backend').value = p.backend || '';
  $('ms-overlay').classList.add('open');
}
function closeSettings() { $('ms-overlay').classList.remove('open'); ST.msModel = null; }
window.openSettings = openSettings; window.closeSettings = closeSettings;

function msTab(btn, which) {
  btn.parentElement.querySelectorAll('button').forEach(b => b.classList.toggle('on', b === btn));
  $('ms-basic').style.display = which === 'basic' ? '' : 'none';
  $('ms-adv').style.display = which === 'adv' ? '' : 'none';
}
window.msTab = msTab;

const numOrNull = (id) => { const v = $(id).value.trim(); return v === '' ? null : Number(v); };

async function saveModelSettings() {
  if (!ST.msModel) return;
  const params = {
    context: numOrNull('ms-context') || 32768,
    max_tokens: numOrNull('ms-maxtok') || 4096,
    temperature: numOrNull('ms-temp'),
    top_p: numOrNull('ms-topp'),
    thinking: $('ms-thinking').classList.contains('on'),
    reasoning_effort: $('ms-effort').value || null,
    parallel: numOrNull('ms-parallel'),
    port: numOrNull('ms-port'),
    mtp_drafts: numOrNull('ms-mtpd'),
    mtp_confidence: numOrNull('ms-mtpc'),
    kv_dtype: $('ms-kvdt').value || null,
    prompt_cache_gib: numOrNull('ms-pcache'),
    vision: $('ms-vision').classList.contains('on'),
    backend: $('ms-backend').value || null,
  };
  const r = await call('model_settings_save', { model: ST.msModel, params }).catch(e => ({ error: String(e) }));
  if (r && r.error) { toast('保存失败: ' + r.error); return; }
  const inst = instOf(ST.msModel);
  if (inst && inst.state === 'ready') {
    toast('已保存 · 正在重启该实例生效');
    await call('engine_stop', { model: ST.msModel }).catch(() => {});
    const s = await call('engine_start', { model: ST.msModel }).catch(e => ({ error: String(e) }));
    if (s && s.error) toast('重启失败: ' + s.error);
  } else {
    toast('设置已保存');
  }
  closeSettings();
  setTimeout(refresh, 600);
}

/* ---------- 导航 ---------- */
function switchPage(name) {
  document.querySelectorAll('.nav-item').forEach(n => n.classList.toggle('on', n.dataset.page === name));
  document.querySelectorAll('.page').forEach(p => p.classList.toggle('on', p.id === 'page-' + name));
  if (name === 'models') renderModelsPage();
  if (name === 'chat') { loadChats(); renderChatTop(); }
  if (name === 'metrics') refresh();
  if (name === 'settings') loadSettings();
}

/* ---------- 启动 ---------- */
async function boot() {
  applyTheme('light');
  document.addEventListener('click', (e) => {
    const nav = e.target.closest('.nav-item');
    if (nav) switchPage(nav.dataset.page);
  });
  $('win-theme').addEventListener('click', toggleTheme);
  $('btn-theme2').addEventListener('click', toggleTheme);
  $('btn-newchat').addEventListener('click', newChat);
  $('btn-send').addEventListener('click', send);
  $('chat-text').addEventListener('keydown', (e) => {
    if (e.key === 'Enter' && !e.shiftKey) { e.preventDefault(); send(); }
  });
  $('chat-model').addEventListener('change', renderChatTop);
  $('btn-updcheck').addEventListener('click', doUpdateCheck);
  $('btn-updapply').addEventListener('click', doUpdateApply);
  $('btn-openhf').addEventListener('click', () => call('open_hf_cache', {}).catch(() => {}));
  $('btn-copyapi').addEventListener('click', async () => {
    await call('copy_text', { text: `http://127.0.0.1:${ST.settings.proxy_port || 8080}/v1` }).catch(() => {});
    toast('API 端点已复制到剪贴板');
  });
  $('ms-save').addEventListener('click', saveModelSettings);
  $('ms-reset').addEventListener('click', () => { if (ST.msModel) openSettings(ST.msModel); });
  [['set-ctx', 'default_context'], ['set-parallel', 'parallel'], ['set-pcache', 'prompt_cache_gib']]
    .forEach(([id, key]) => {
      $(id).addEventListener('change', async () => {
        ST.appset = await call('app_settings_save', { [key]: Number($(id).value) }).catch(() => ST.appset);
        toast('已保存');
      });
    });
  [['set-autostart', 'autostart_engine'], ['set-updcheck', 'auto_update_check'],
   ['set-menubar', 'menubar'], ['set-close2mb', 'close_to_menubar']].forEach(([id, key]) => {
    $(id).addEventListener('click', async () => {
      const on = !$(id).classList.contains('on');
      $(id).classList.toggle('on', on);
      ST.appset = await call('app_settings_save', { [key]: on }).catch(() => ST.appset);
    });
  });

  ST.family = await call('families', {}).catch(() => []);
  try { ST.cache = await call('models_installed', {}); } catch (e) {}
  try { ST.appset = await call('app_settings_get', {}); } catch (e) {}
  if (ST.appset.theme === 'dark' || (!ST.appset.theme && matchMedia('(prefers-color-scheme: dark)').matches)) applyTheme('dark');
  renderCards();
  renderCacheList();
  loadChats();
  await refresh();

  setInterval(refresh, 2500);
}

document.addEventListener('DOMContentLoaded', boot);
