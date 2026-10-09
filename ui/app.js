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

// 带超时的桥调用：settings 里含 pool.detect()（会 spawn 一次子进程），
// 实测冷启动时该调用可能长时间不返回；桥本身无超时保护，一旦不返回，
// 任何 await 它的地方（含 boot）都会永久挂住。
function callTimeout(method, args, ms) {
  return Promise.race([
    call(method, args),
    new Promise((_, rej) => setTimeout(() => rej(new Error('bridge timeout: ' + method)), ms || 15000)),
  ]);
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
    ST.lastOv = ov;
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
  const S = ST.settings || {};
  const eng = (ST.upd && ST.upd.engine) || {}, app = (ST.upd && ST.upd.app) || {};
  ver.childNodes[0].nodeValue = 'v' + (S.app_version || '—');
  vtip.textContent = eng.available ? `引擎有新版本 v${eng.latest}，设置页一键升级`
    : app.available ? `App 有新版本 v${app.latest}`
    : `引擎 ${S.version || '—'} · 已是最新`;
  ver.classList.toggle('new', !!(eng.available || app.available));
}

// 后台加载版本信息（settings 含 pool.detect()，冷启动可能慢/不返回 → 必须带超时且不可 await）。
// 取到后立刻回填顶栏与监控页版本行；失败则稍后重试（最多 3 次），仍失败就保持 "—"。
let _verLoading = false;
async function loadVersions(tries) {
  if (_verLoading) return;
  tries = tries == null ? 3 : tries;
  _verLoading = true;
  let ok = false;
  try {
    const s = await callTimeout('settings', {}, 15000);
    if (s && typeof s === 'object') { ST.settings = s; ok = true; }
  } catch (e) { /* 超时/失败 */ }
  _verLoading = false;
  if (!ok) {
    if (tries > 1) setTimeout(() => loadVersions(tries - 1), 4000);
    return;
  }
  const ov = ST.lastOv;
  if (ov) {
    renderTopbar(ov);
    if ($('page-metrics').classList.contains('on')) renderMetrics(ov);
  }
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
  // 每次都重取官方模型表：卡片上的加速配套（草稿模型有没有下载）会随下载/删除变化，
  // 只在表为空时取的话，下完草稿模型再回到这一页，卡片口径还停在旧值。
  try { const fam = await call('families', {}); if (fam && fam.length) ST.family = fam; } catch (e) {}
  try { ST.cache = await call('models_installed', {}); } catch (e) {}
  try { ST.pulls = await call('pull_status', {}); } catch (e) {}
  renderCards();
  renderCacheList();
  renderBadge();
}

const instOf = (id) => ST.inst.find(i => i.model === id);
const cacheOf = (id) => ST.cache.find(m => m.ref === id || m.id === id);
// 展示名去 provider：TensorFold/Qwen3.8-27B-MLX-4bit → Qwen3.8-27B-MLX-4bit；本地路径取末段
const shortName = (ref) => { const s = String(ref || '').replace(/\/+$/, ''); return s.split('/').pop() || s; };

function renderCards() {
  $('mcards').innerHTML = ST.family.map(f => {
    const inst = instOf(f.id), cached = cacheOf(f.id), pull = (ST.pulls || {})[f.id];
    const badges = [];
    if (inst && inst.state === 'ready') badges.push('<span class="badge run">● 运行中</span>');
    else if (inst && inst.state === 'starting') badges.push('<span class="badge own">◌ 启动中</span>');
    else if (inst && inst.state === 'error') badges.push('<span class="badge" style="background:var(--danger-bg);color:var(--danger)">✕ 异常</span>');
    // 实际在跑的引擎：升级后一眼看出有没有真的换过去（native / 回退的解释器）
    if (inst && inst.launcher && inst.state !== 'idle') badges.push(`<span class="badge own" title="${esc(inst.launcher_path || '')}">${esc(inst.launcher)}</span>`);
    if (pull) badges.push('<span class="badge own" style="color:var(--dl-ink)">下载中</span>');
    else if (cached) badges.push('<span class="badge own">已缓存</span>');

    let sz, prog = '';
    if (pull) {
      prog = '<div class="prog"><i style="width:34%"></i></div>';
      sz = '下载中 · tensorfold pull';
    } else if (cached) sz = `${fmt0(cached.size_gb)} GB`;
    else sz = f.size_gb ? `未缓存 · 下载约 ${fmt0(f.size_gb)} GB` : '未缓存';

    const running = !!(inst && inst.state !== 'idle');
    const loadBtn = running
      ? '<button class="sbtn" disabled>加载</button>'
      : (cached
          ? `<button class="sbtn" onclick="loadModel('${esc(f.id)}')">加载</button>`
          : `<button class="sbtn pri" onclick="loadModel('${esc(f.id)}')">↓ 下载</button>`);
    const delBtn = (cached && !running)
      ? `<button class="sbtn del" onclick="delModel('${esc(f.id)}')">删除</button>`
      : `<button class="sbtn del" disabled${running ? ' title="运行中不可删"' : ''}>删除</button>`;
    // 加速配套 chip：把「官方支持模型」与缓存里的辅助模型联起来 —— 卡片上直接看到
    // 草稿模型叫什么、有没有下载，点一下进设置配置。刻意用 span 而非 .sbtn：
    // 卡片按钮数是原型闸门锁死的（加载/设置/删除三枚）。
    const acc = f.accel || {};
    let accelChip = '';
    if (acc.draft_repo) {
      const dn = esc(shortName(acc.draft_repo));
      accelChip = acc.draft_cached
        ? `<div class="accline"><span class="accelchip on" title="草稿模型 ${esc(acc.draft_repo)} 已下载${acc.draft_size_gb ? '（' + fmt0(acc.draft_size_gb) + ' GB）' : ''} · 点击配置" onclick="openSettings('${esc(f.id)}')">⚡ 草稿加速已就绪<span class="ar">· ${dn}</span></span></div>`
        : `<div class="accline"><span class="accelchip off" title="草稿模型 ${esc(acc.draft_repo)} 未下载 · 点击进设置下载" onclick="openSettings('${esc(f.id)}')">⚡ 草稿模型未下载<span class="ar">· 点此配置</span></span></div>`;
    }
    return `<div class="mcard${inst && inst.state === 'ready' ? ' active' : ''}">
      <div class="mt"><b>${esc(f.name)}</b>${badges.join('')}</div>
      <div class="rid" title="${esc(f.id)}">${esc(shortName(f.id))}</div>
      <div class="desc">${esc(f.note || '')}</div>
      ${accelChip}
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
  if (!ST.cache.length) { box.innerHTML = '<div class="empty" style="padding:13px 16px;color:var(--ink4)">没有扫到模型，去设置页「模型目录」加一个目录，或点上方「↓ 下载」拉官方模型</div>'; return; }
  const officialIds = new Set((ST.family || []).map(f => f.id));
  box.innerHTML = ST.cache.map(m => {
    const inst = instOf(m.ref), running = inst && inst.alive;
    // 只允许删 HF 缓存里下载的（外部目录的权重是用户自己的资料，App 不碰）
    const del = m.deletable
      ? `<button class="sbtn del" ${running ? 'disabled title="运行中不可删"' : `onclick="delModel('${esc(m.ref)}')"`}>删除</button>`
      : '<span style="color:var(--ink4)" title="外部目录（oMLX/MTPLX/自定义），本 App 不删除">外部</span>';
    // 非官方宣传的模型（不在官方族列表里）也能一键开启：这就是"可以使用就给出开启选项"
    const official = officialIds.has(m.id) || officialIds.has(m.ref);
    // 辅助（草稿）模型：它是主模型的推测解码配套，不能单独开启 —— 单开只会把它当主模型
    // 加载（必然失败）。所以这里不给「开启」，改标「辅助模型」并联到主模型的设置里去配置。
    const isDraft = m.role === 'draft';
    const loadOrStop = isDraft
      ? (m.used_by && m.used_by.length
          ? `<button class="sbtn" onclick="openSettings('${esc(m.used_by[0])}')">用于 ${esc(shortName(m.used_by[0]))}</button>`
          : '')
      : (running
          ? '<span class="mini-chip" style="color:var(--run-ink)">● 运行中</span>'
          : `<button class="sbtn" onclick="loadModel('${esc(m.ref)}')">开启</button>`);
    const roleTag = isDraft
      ? '<span class="tag draft" title="推测解码用的草稿模型，不能单独开启；在上方主模型的设置里启用或关闭">辅助模型</span>'
      : (official ? '' : '<span class="tag" style="color:var(--warn)">非官方</span>');
    return `<div class="pitem"><span class="dot ${isDraft ? 'off' : (running ? 'on' : 'off')}"></span>`
      + `<span class="tag">${esc(m.root_label || m.source || '')}</span>`
      + `<span class="mono" title="${esc(m.ref)}">${esc(shortName(m.id))}</span>`
      + roleTag
      + `<span class="right">${fmt0(m.size_gb)} GB${loadOrStop}${del}</span></div>`;
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
  const ready = ST.inst.filter(i => i.state === 'ready' || i.state === 'starting');
  const cur = sel.value;
  // 可选池 = ready/starting 实例 + 本机已有模型（含 oMLX/MTPLX/自定义目录；未加载的发送时自动拉起）
  // 统一用 ref 作为身份：HF 模型 = owner/name，外部目录模型 = 绝对路径
  const cachedRefs = ST.cache.map(m => m.ref);
  const poolIds = [...new Set([...ready.map(i => i.model), ...cachedRefs])];
  sel.innerHTML = poolIds.length
    ? poolIds.map(id => {
        const st = ready.find(i => i.model === id);
        const tag = st ? (st.state === 'ready' ? '' : '（加载中…）') : '（未加载 · 发送时自动拉起）';
        return `<option value="${esc(id)}">${esc(id.split('/').pop())}${tag}</option>`;
      }).join('')
    : '<option value="">（没有可用模型，去模型页下载）</option>';
  if (poolIds.includes(cur)) sel.value = cur;
  else if (ST.cur && ST.cur.model && poolIds.includes(ST.cur.model)) sel.value = ST.cur.model;
  const inst = ready.find(i => i.model === sel.value);
  $('chat-ctx').textContent = inst && inst.params && inst.params.context ? `ctx ${(inst.params.context / 1024) | 0}k` : 'ctx —';
}

/* 对话前确保模型已加载：未 ready 则 engine_start 并轮询至 ready/starting 结束 */
async function ensureModelReady(model) {
  const inst = ST.inst.find(i => i.model === model);
  if (inst && inst.state === 'ready') return true;
  toast(`正在加载 ${model.split('/').pop()} …（约 30s）`);
  const r = await call('engine_start', { model }).catch(e => ({ error: String(e) }));
  if (r && r.error) { toast('加载失败: ' + r.error); return false; }
  // 轮询最多 ~150s（大模型冷启动）
  for (let i = 0; i < 50; i++) {
    await new Promise(res => setTimeout(res, 3000));
    try {
      const ov = await call('overview', {});
      ST.inst = ov.instances || [];
    } catch (e) {}
    const cur = ST.inst.find(x => x.model === model);
    if (cur && cur.state === 'ready') { refresh(); return true; }
    if (cur && cur.state === 'error') { toast('模型加载失败，见引擎日志'); return false; }
  }
  toast('加载超时，可稍后重发');
  return false;
}

async function send() {
  const ta = $('chat-text');
  const text = ta.value.trim();
  let model = $('chat-model').value;
  if (!text || ST.streaming) return;
  if (!model) { toast('请先在模型页下载一个模型'); return; }
  // 选中的未加载模型：发送即自动拉起（2026-10-08 需求 4）
  const inst = ST.inst.find(i => i.model === model);
  if (!inst || inst.state !== 'ready') {
    const okStart = await ensureModelReady(model);
    if (!okStart) { refresh(); return; }
  }
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
  $('st-prefill').innerHTML = (L.prefill_tps != null ? fmtNum(L.prefill_tps) : '—') + '<small>tok/s</small>';
  $('st-mem').innerHTML = (L.footprint_gb != null ? fmt0(L.footprint_gb) : '—') + (L.footprint_gb != null ? '<small>GB</small>' : '');
  $('st-free').innerHTML = (ov.mem_free != null ? fmt0(ov.mem_free) : '—') + (ov.mem_free != null ? `<small>GB / ${fmt0(ov.mem_total)}GB</small>` : '');
  $('st-kv').innerHTML = (L.kv != null ? fmt0(L.kv) : '—') + '<small>%</small>';
  $('st-req').innerHTML = (L.running != null ? L.running : '—') + '<small>活跃</small>';
  $('st-req-sub').textContent = `${L.running || 0} 活跃 · ${L.waiting || 0} 排队`;
  const ratios = Object.values(per).map(p => p.accepted_ratio).filter(v => v != null);
  $('st-mtp').innerHTML = ratios.length ? Math.round(Math.max(...ratios) * 100) + '<small>%</small>' : '—';
  const nReady = ST.inst.filter(i => i.state === 'ready').length;
  $('st-inst').textContent = nReady;

  // ---- 用量行（可分行显示：请求 / token 总数 / 提示 / 输出 / 已缓存）----
  const promptTok = L.prompt_tokens || 0, genTok = L.gen_tokens_total || 0;
  $('st-reqs-done').textContent = fmtInt(L.requests_done);
  $('st-tok-all').textContent = fmtInt(promptTok + genTok);
  $('st-tok-prompt').textContent = fmtInt(promptTok);
  $('st-tok-gen').textContent = fmtInt(genTok);
  // 已缓存 token（估算）：Σ 每实例 kv_ratio × context；引擎未直接暴露 cached 计数
  let cachedTok = 0, totalCtx = 0;
  ST.inst.filter(i => i.state === 'ready').forEach(i => {
    const p = per[i.model] || {}, ctx = (i.params && i.params.context) || 0;
    if (ctx && p.kv != null) { cachedTok += ctx * (p.kv / 100); totalCtx += ctx; }
  });
  $('st-tok-cached').textContent = cachedTok ? fmtInt(Math.round(cachedTok)) : '—';
  $('st-tok-cached-sub').textContent = cachedTok ? `KV 池驻留 · 上下文 ${fmtInt(totalCtx)}` : '需运行中实例';
  // 缓存效率 = 已缓存 / 提示总量（>100% 说明跨请求复用，钳到 999%）
  const eff = (promptTok > 0 && cachedTok) ? Math.min(cachedTok / promptTok * 100, 999) : null;
  $('st-cache-eff').innerHTML = eff != null ? Math.round(eff) + '<small>%</small>' : '—';
  $('st-cache-eff').parentElement.querySelector('.sub').textContent =
    eff != null ? (cachedTok >= promptTok ? '跨请求复用生效' : '缓存命中 / 提示总量') : '等待首条请求';

  // ---- 本机性能行 ----
  $('st-cpu').innerHTML = (L.cpu_percent != null ? Math.round(L.cpu_percent) : '—') + '<small>%</small>';
  $('st-gpu').innerHTML = (L.gpu_percent != null ? Math.round(L.gpu_percent) : '—') + '<small>%</small>';
  const usedGb = (ov.mem_total != null && ov.mem_free != null) ? Math.max(0, ov.mem_total - ov.mem_free) : null;
  $('st-hostmem').innerHTML = usedGb != null ? fmt0(usedGb) + '<small> / ' + fmt0(ov.mem_total) + 'GB</small>' : '—';
  $('st-cpu-sub').textContent = ov.cpu_cores ? `${ov.cpu_cores} 核 · 整机占用` : '整机占用';
  // 版本行：App + 引擎（升级后引擎版本即时更新）
  const SS = ST.settings || {};
  $('host-versions').textContent = `App v${SS.app_version || '—'} · 引擎 ${SS.version || '未安装'}`;
  // 冷热缓存：checkpoint 预算（prompt_cache_gib）占用口径，无精确命中数时标注估算
  const pc = ST.appset && ST.appset.prompt_cache_gib;
  $('host-cache-tier').textContent = pc ? `Prompt 缓存预算 ${pc} GiB · 热驻留（KV/快照），冷数据落盘自动换页` : '热：KV/快照驻留显存 · 冷：落盘自动换页';

  bars('bars-tps', (S.tps || {}).values, v => v);
  bars('bars-mem', (S.footprint_gb || {}).values, v => v);
  bars('bars-free', (S.mem_free || {}).values, v => v, true);
  bars('bars-cpu', (S.cpu_percent || {}).values, v => v);
  bars('bars-gpu', (S.gpu_percent || {}).values, v => v);

  const vals = ((S.tps || {}).values || []).slice(-60);
  const svg = $('chart-tps');
  const chartEmpty = $('chart-tps-empty');
  if (vals.length >= 2) {
    const max = Math.max(...vals, 1);
    const pts = vals.map((v, i) => `${(i / (vals.length - 1)) * 520},${110 - (v / max) * 100}`).join(' ');
    svg.innerHTML = `<g stroke="var(--line)" stroke-width="1"><line x1="0" y1="27" x2="520" y2="27"/><line x1="0" y1="55" x2="520" y2="55"/><line x1="0" y1="82" x2="520" y2="82"/></g><polyline fill="none" stroke="var(--ok)" stroke-width="2" points="${pts}"/>`;
    if (chartEmpty) chartEmpty.classList.remove('on');
  } else {
    // 空态不写 SVG <text>：该 svg 非等比拉伸会把文字压扁，改用 HTML 覆盖层
    svg.innerHTML = '';
    if (chartEmpty) chartEmpty.classList.add('on');
  }

  $('inst-list').innerHTML = ST.inst.length ? ST.inst.map(i =>
    `<div class="pitem"><span class="dot ${i.state === 'ready' ? 'on' : 'off'}"></span><span class="mono">${esc(i.model)}</span><span class="right">:${i.port} · ${i.state}${i.uptime ? ' · ' + fmtUp(i.uptime) : ''} · ${i.params && i.params.context ? fmtK(i.params.context) : '—'}<button class="sbtn del" ${i.state === 'idle' ? 'disabled' : `onclick="stopModel('${esc(i.model)}')"`}>停止</button></span></div>`).join('')
    : '<div class="empty" style="padding:13px 16px;color:var(--ink4)">没有引擎实例，去模型页点「加载」</div>';
}

const fmtInt = (v) => v == null ? '—' : Number(v).toLocaleString('en-US');

// 展示型数值统一 0 位小数（用户 2026-10-09 要求：所有读数不留小数）
const fmt0 = (v) => v == null || Number.isNaN(Number(v)) ? '—' : String(Math.round(Number(v)));
// 速度类：<10000 直接给整数千分位（保留精度且无小数），≥10000 折成 Nk
const fmtNum = (v) => v == null ? '—' : (Number(v) >= 10000
  ? Math.round(Number(v) / 1000) + 'k' : Math.round(Number(v)).toLocaleString('en-US'));
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
    const def = (ST.appset && ST.appset.default_model) || (ST.cache[0] && ST.cache[0].ref);
    if (!def) { toast('没有可用模型，去模型页下载一个，或在设置页加模型目录'); switchPage('models'); return; }
    toast(`正在加载 ${String(def).split('/').pop()} …`);
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
  try { ST.settings = (await callTimeout('settings', {}, 15000)) || ST.settings || {}; }
  catch (e) { ST.settings = ST.settings || {}; }   // 超时不阻塞设置页
  const last = ST.upd && ST.upd.checked_at ? ' · 上次检查 ' + fmtTime(ST.upd.checked_at) : '';
  $('ver-sub').textContent = `App v${ST.settings.app_version || '—'} · 引擎 ${ST.settings.version || '未安装'}${last}`;
  $('btn-copyapi').textContent = `http://127.0.0.1:${ST.settings.proxy_port || 8080}/v1 ⧉`;
  renderUpdate();
  await refreshScanDirs();
}

/* ---------- 模型目录（扫描根） ---------- */
async function refreshScanDirs() {
  ST.scan = await call('scan_dirs', {}).catch(() => ST.scan || {});
  renderScanRoots();
}

function renderScanRoots() {
  const box = $('scan-roots');
  if (!box) return;
  const s = ST.scan || {};
  const roots = s.roots || [];
  box.innerHTML = roots.map(r => {
    const cnt = r.exists
      ? `<span class="cnt">${r.count} 个模型</span>`
      : '<span class="miss">目录不存在</span>';
    const rm = r.custom
      ? `<button class="sbtn del" onclick="removeScanDir('${esc(r.path)}')">移除</button>`
      : '<span style="color:var(--ink4);flex:none">内置</span>';
    return `<div class="pitem"><span class="tag${r.custom ? ' custom' : ''}">${esc(r.label)}</span>`
      + `<span class="pth" title="${esc(r.path)}">${esc(r.path)}</span>${cnt}${rm}</div>`;
  }).join('') + `<div class="pitem"><span class="tag">合计</span><span class="pth">共扫到 ${s.found || 0} 个模型（模型页「本机缓存」可见）</span></div>`;
}

window.addScanDir = async function (path) {
  const p = (path != null ? path : ($('scan-path') || {}).value || '').trim();
  if (!p) { toast('先填目录路径，或点「选择…」'); return; }
  const r = await call('scan_dir_add', { path: p }).catch(e => ({ error: String(e) }));
  if (!r || r.ok === false) { toast('添加失败: ' + (r && r.error)); return; }
  $('scan-path').value = '';
  toast(r.added === false ? '该目录已在列表中' : `已添加，共扫到 ${r.found || 0} 个模型`);
  ST.scan = r;
  renderScanRoots();
  await refreshModelsOnly();
};

window.removeScanDir = async function (path) {
  const r = await call('scan_dir_remove', { path }).catch(e => ({ error: String(e) }));
  if (!r || r.ok === false) { toast('移除失败: ' + (r && r.error)); return; }
  toast('已移除');
  ST.scan = r;
  renderScanRoots();
  await refreshModelsOnly();
};

async function pickScanDir() {
  const r = await call('pick_dir', {}).catch(e => ({ error: String(e) }));
  if (!r || r.ok === false) { if (r && r.error) toast(r.error); return; }
  addScanDir(r.path);
}

async function refreshModelsOnly() {
  try { ST.cache = await call('models_installed', {}); } catch (e) {}
  renderCacheList();
  renderChatTop();
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
  try { ST.settings = (await callTimeout('settings', {}, 15000)) || ST.settings || {}; } catch (e) {}
  loadSettings();
  renderTopbar(await call('overview', {}).catch(() => ({ instances: [] })));
}

async function doUpdateApply() {
  const eng = (ST.upd.engine || {});
  if (eng.available) {
    if (!confirm(`升级引擎到 v${eng.latest}？\n将从 GitHub 拉取覆盖安装；升级完成后会自动用新引擎重载当前运行中的模型。`)) return;
    toast('正在从 GitHub 拉取安装（可能需要 1-2 分钟）…');
    const r = await call('update_apply_engine', {}).catch(e => ({ error: String(e) }));
    toast(r && r.ok ? `已升级到 ${r.version}${r.restarted_hint ? '，' + r.restarted_hint : ''}` : '升级失败: ' + (r && r.error));
  } else if ((ST.upd.app || {}).url) {
    call('update_open_app', {}).catch(() => {});
    toast('已在浏览器打开 App 下载页');
  }
}

/* ---------- 模型属性区（设置弹窗基础段顶部） ---------- */
// 画像来源：后端 model_meta(ref) 读模型自身 config.json；没读到就退化成“引擎默认”提示。
const fmtK = (n) => (n == null ? '—' : n >= 1024 ? `${Math.round(n / 1024)}k` : String(n));

function renderAttrs(meta) {
  const box = $('ms-attrs');
  if (!meta || !meta.found) {
    box.innerHTML = '<span class="at dim">未读到模型 config.json — 输入/输出上限用引擎默认</span>';
    return;
  }
  const cap = meta.capabilities || {}, acc = meta.accel || {}, d = meta.defaults || {};
  const items = [];
  items.push(`<span class="at dim"><span class="k">架构</span>${esc(meta.model_type || '—')}</span>`);
  items.push(`<span class="at dim"><span class="k">输入上限</span>${fmtK(d.context ?? meta.context_max)} tok</span>`);
  items.push(cap.vision
    ? '<span class="at on">● 支持图像</span>'
    : '<span class="at off">○ 不支持图像</span>');
  items.push(cap.mtp
    ? `<span class="at on">● 内置 MTP 头${acc.mtp_layers ? '（' + acc.mtp_layers + ' 层）' : ''}</span>`
    : '<span class="at dim">无内置 MTP 头</span>');
  if (acc.draft_repo) {
    const sz = acc.draft_size_gb ? ' ' + fmt0(acc.draft_size_gb) + ' GB' : '';
    items.push(acc.draft_cached
      ? `<span class="at on" title="${esc(acc.draft_repo)}">● 草稿模型已下载${sz}</span>`
      : `<span class="at warn" title="tensorfold pull ${esc(acc.draft_repo)}">○ 草稿模型未下载</span>`);
  }
  box.innerHTML = items.join('');
}

/* ---------- 加速配套区块（设置弹窗基础段） ---------- */
// 以前这里只有一枚只读徽标「草稿模型已下载」：看不到是哪个模型、多大、也没法开或关。
// 现在把它变成可配置区块：草稿模型全名 + 状态/体积 + 一键下载 + 推测解码总开关。
function renderAccel(meta, p) {
  const box = $('ms-accel');
  if (!box) return;
  const acc = (meta && meta.accel) || {};
  const draftRepo = acc.draft_repo || '';
  if (!meta || !meta.found || (!draftRepo && !acc.builtin_mtp)) {
    box.style.display = 'none';
    box.innerHTML = '';
    return;
  }
  box.style.display = '';
  const pulling = !!(ST.pulls || {})[draftRepo];
  const rows = [];
  if (acc.builtin_mtp) {
    rows.push('<div class="arow"><span class="aname">内置 MTP 头</span>'
      + `<span class="astate on">● ${acc.mtp_layers ? acc.mtp_layers + ' 层' : '可用'}</span></div>`);
  }
  if (draftRepo) {
    const st = pulling
      ? '<span class="astate off">◌ 下载中</span>'
      : acc.draft_cached
        ? `<span class="astate on">● 已下载${acc.draft_size_gb ? ' ' + fmt0(acc.draft_size_gb) + ' GB' : ''}</span>`
        : '<span class="astate off">○ 未下载</span>';
    rows.push(`<div class="arow"><span class="aname" title="${esc(draftRepo)}">${esc(draftRepo)}</span>${st}</div>`);
    if (!acc.draft_cached && !pulling) {
      rows.push('<div class="abtns">'
        + `<button class="sbtn pri" onclick="pullDraft('${esc(draftRepo)}')">↓ 下载草稿模型</button>`
        + `<span class="acode">tensorfold pull ${esc(draftRepo)}</span></div>`);
    }
    rows.push('<div class="anote">草稿模型用于推测解码：每轮先猜几个 token 再由主模型校验，'
      + '输出与逐个解码一致、通常更快。尚未下载时引擎自动只用内置 MTP 头。</div>');
  }
  const on = p ? p.drafts !== false : true;   // 缺省 = 开
  rows.push('<div class="arow"><span class="aname" style="font-family:inherit;font-size:12.5px;color:var(--ink2)">'
    + '启用推测解码<div class="hint2">--no-drafts · 关掉后内置 MTP 与草稿模型一并停用</div></span>'
    + `<span class="switch${on ? ' on' : ''}" id="ms-drafts" onclick="toggleSwitch(this)"></span></div>`);
  box.innerHTML = '<div class="ah">加速配套</div>' + rows.join('');
}

/* 弹窗里的开关统一走这里。此前 #ms-thinking / #ms-vision 没绑任何点击处理，
   点上去毫无反应（开关是死的），保存时也只能读到初始值。 */
window.toggleSwitch = function (el) { if (el) el.classList.toggle('on'); };

/* 下载辅助（草稿）模型：复用模型页那条 pull 链路，下完刷新弹窗状态 */
window.pullDraft = async function (repo) {
  toast(`开始下载草稿模型 ${repo}（后台进行，可继续操作）`);
  const r = await call('model_pull', { repo_id: repo }).catch(e => ({ error: String(e) }));
  if (r && r.error) { toast('下载失败: ' + r.error); return; }
  // 卡片上的加速 chip 取自 families，这里同步刷新一次，免得退出弹窗后还是旧口径
  try { const fam = await call('families', {}); if (fam && fam.length) ST.family = fam; } catch (e) {}
  renderCards();
  if (ST.msModel) await openSettings(ST.msModel);
};

/* ---------- 模型设置弹窗 ---------- */
async function openSettings(model) {
  ST.msModel = model;
  $('ms-title').textContent = '模型设置 — ' + model.split('/').pop();
  let p = {}, meta = null;
  try { p = await call('model_settings_get', { model }); } catch (e) {}
  try { meta = await call('model_info', { ref: model }); } catch (e) {}
  ST.msMeta = meta;
  renderAttrs(meta);
  try { ST.pulls = await call('pull_status', {}); } catch (e) {}
  renderAccel(meta, p);
  // 初始值 = 模型自身默认配置（用户可改）；用户显式存过的字段优先。
  // 后端把「显式存过哪些键」放在 _raw（合并默认值后的 p 无法区分二者）。
  const raw = (p && p._raw) || {};
  const defCtx = (meta && meta.defaults && meta.defaults.context) || 32768;
  const defTok = (meta && meta.defaults && meta.defaults.max_tokens) || 4096;
  $('ms-context').value = raw.context != null ? p.context : defCtx;
  $('ms-maxtok').value = raw.max_tokens != null ? p.max_tokens : defTok;
  const ctxHint = $('ms-ctx-hint'), tokHint = $('ms-maxtok-hint');
  if (ctxHint) ctxHint.textContent = `--context · 输入上限${meta && meta.context_max ? '（模型 ' + fmtK(meta.context_max) + '）' : ''}`;
  if (tokHint) tokHint.textContent = '--max-tokens · 输出上限';
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
  // 视觉开关按模型能力限制：不支持图像的模型禁用并标注（保存时也不会上报 vision=true）
  const vrow = $('ms-vision');
  const visionSupported = !meta || !meta.found || !!(meta.capabilities || {}).vision;
  if (vrow) {
    if (!visionSupported) vrow.classList.remove('on');
    vrow.classList.toggle('disabled', !visionSupported);
    vrow.title = visionSupported ? '模型支持图像输入' : '该模型 config 未声明视觉能力，不可开启';
  }
  $('ms-backend').value = p.backend || '';
  $('ms-overlay').classList.add('open');
}
function closeSettings() { $('ms-overlay').classList.remove('open'); ST.msModel = null; }
window.openSettings = openSettings; window.closeSettings = closeSettings;

/* 模型默认：把输入/输出上限与采样回填为模型自身 config 的默认（用户可再改，不自动保存） */
function applyRecommended() {
  if (!ST.msModel) return;
  const meta = ST.msMeta;
  const d = (meta && meta.defaults) || {};
  if (meta && meta.found && d.context) {
    $('ms-context').value = d.context;
    $('ms-maxtok').value = d.max_tokens != null ? d.max_tokens : '';
    $('ms-temp').value = d.temperature != null ? d.temperature : '';
    $('ms-topp').value = d.top_p != null ? d.top_p : '';
    toast(`已回填模型默认：输入上限 ${fmtK(d.context)} tok、temperature ${d.temperature ?? '默认'}、top_p ${d.top_p ?? '默认'}，确认后保存`);
    return;
  }
  // 没读到模型 config：按体积给保守起点（旧行为兜底）
  const cached = cacheOf(ST.msModel);
  const gb = cached && cached.size_gb ? cached.size_gb : (ST.family.find(f => f.id === ST.msModel) || {}).size_gb;
  const ctx = !gb ? 32768 : gb < 10 ? 65536 : gb < 20 ? 32768 : gb < 40 ? 16384 : 8192;
  $('ms-context').value = ctx;
  if ($('ms-maxtok').value === '' || Number($('ms-maxtok').value) > 8192) $('ms-maxtok').value = 4096;
  toast(`未读到模型 config，按体积给保守值：上下文 ${ctx / 1024 | 0}k（约 ${gb ? fmt0(gb) : '?'} GB）`);
}
window.applyRecommended = applyRecommended;

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
    // 留空 = 不传旗标 = 引擎按模型默认自决（不再是写死的 32768/4096）
    context: numOrNull('ms-context'),
    max_tokens: numOrNull('ms-maxtok'),
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
  // 推测解码总开关：只有模型确实有加速配套（草稿模型 / 内置 MTP）时才上报，
  // 免得给无关模型平白写一个 drafts 覆盖项。对应引擎 --no-drafts。
  if ($('ms-drafts')) params.drafts = $('ms-drafts').classList.contains('on');
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
  $('btn-adddir').addEventListener('click', () => addScanDir());
  $('btn-pickdir').addEventListener('click', pickScanDir);
  $('scan-path').addEventListener('keydown', (e) => { if (e.key === 'Enter') addScanDir(); });
  $('btn-copyapi').addEventListener('click', async () => {
    await call('copy_text', { text: `http://127.0.0.1:${ST.settings.proxy_port || 8080}/v1` }).catch(() => {});
    toast('API 端点已复制到剪贴板');
  });
  $('ms-save').addEventListener('click', saveModelSettings);
  // 恢复默认 = 清掉该模型已存的覆盖项，回到「模型自身默认配置」
  $('ms-reset').addEventListener('click', async () => {
    if (!ST.msModel) return;
    await call('model_settings_reset', { model: ST.msModel }).catch(() => {});
    await openSettings(ST.msModel);
    toast('已恢复为模型默认配置（未保存，点「保存并重启引擎」生效）');
  });
  $('ms-recommend').addEventListener('click', applyRecommended);
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

  switchPage('metrics');   // 默认页=监控（2026-10-08 定序）
  // 版本信息：旧版只在打开设置页时才取 settings，于是监控页的「软件版本」
  // 长期显示 "App v— · 引擎 未安装"、顶栏回退到写死版本号。
  // 这里改为启动即后台加载 —— 但**绝不能 await**：settings 内含 pool.detect()
  // （spawn 子进程），冷启动时可能长时间不返回，await 会把整个 boot 挂死，
  // 后半段的 renderCards/refresh/setInterval 全部不执行。
  loadVersions();
  ST.family = await call('families', {}).catch(() => []);
  try { ST.cache = await call('models_installed', {}); } catch (e) {}
  try { ST.appset = await call('app_settings_get', {}); } catch (e) {}
  if (ST.appset.theme === 'dark' || (!ST.appset.theme && matchMedia('(prefers-color-scheme: dark)').matches)) applyTheme('dark');
  renderCards();
  renderCacheList();
  loadChats();
  refreshScanDirs();
  await refresh();

  setInterval(refresh, 2500);
}

document.addEventListener('DOMContentLoaded', boot);
