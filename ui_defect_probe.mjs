// v2.0.1 缺陷复现：长文本下字符重叠 / 按钮遮挡 DOM 级检测（模式与 ui_conformance.mjs 一致）
import { spawn } from 'child_process';
import http from 'http';
import fs from 'fs';
import path from 'path';

const ROOT = path.dirname(new URL(import.meta.url).pathname);
const MOCK = fs.readFileSync(path.join(ROOT, 'ui', 'mock_bridge.js'), 'utf-8');

const srv = http.createServer((req, res) => {
  let f = path.join(ROOT, 'ui', decodeURIComponent(req.url.split('?')[0]));
  if (f.endsWith('/')) f += 'index.html';
  try {
    const b = fs.readFileSync(f);
    const type = f.endsWith('.css') ? 'text/css' : f.endsWith('.js') ? 'text/javascript' : 'text/html; charset=utf-8';
    res.writeHead(200, { 'Content-Type': type });
    res.end(b);
  } catch { res.writeHead(404); res.end('nf'); }
});
await new Promise(r => srv.listen(8899, '127.0.0.1', r));

const CHROME = '/Applications/Google Chrome.app/Contents/MacOS/Google Chrome';
const PORT = 9335;
const chrome = spawn(CHROME, ['--headless=new', '--no-sandbox', '--disable-gpu',
  '--remote-debugging-port=' + PORT, '--no-first-run', '--no-proxy-server',
  '--user-data-dir=/tmp/tfprobe-cdp', 'about:blank'], { stdio: 'ignore' });
await new Promise(r => setTimeout(r, 2000));

function cdp(wsUrl) {
  const ws = new WebSocket(wsUrl); let id = 0; const pend = {};
  return new Promise(res => {
    ws.onopen = () => {
      const api = { send(m, p = {}) { return new Promise(r => { const i = ++id; pend[i] = r; ws.send(JSON.stringify({ id: i, method: m, params: p })); }) } };
      ws.onmessage = e => { const d = JSON.parse(e.data); if (d.id && pend[d.id]) { pend[d.id](d.result ?? d, d); delete pend[d.id]; } };
      res(api);
    };
  });
}
async function newPage(url) {
  const r = await fetch(`http://127.0.0.1:${PORT}/json/new?${encodeURIComponent(url)}`, { method: 'PUT' });
  return r.json();
}
const p = await newPage('about:blank');
const c = await cdp(p.webSocketDebuggerUrl);
await c.send('Page.enable');
await c.send('Runtime.enable');
await c.send('Page.addScriptToEvaluateOnNewDocument', { source: MOCK });
await c.send('Emulation.setDeviceMetricsOverride', { width: 900, height: 600, deviceScaleFactor: 1, mobile: false });
await c.send('Page.navigate', { url: 'http://127.0.0.1:8899/index.html' });
await new Promise(r => setTimeout(r, 1800));

let pass = 0, fail = 0;
function ok(name, cond, detail) { if (cond) { pass++; console.log('PASS', name); } else { fail++; console.log('FAIL', name, detail || ''); } }
async function ev(expr) {
  const r = await c.send('Runtime.evaluate', { expression: expr, returnByValue: true, awaitPromise: true });
  if (r?.exceptionDetails) return { __err: r.exceptionDetails.text + ' ' + JSON.stringify(r.exceptionDetails.exception?.description || '') };
  return r?.result?.value;
}

// ====== 注入极端数据并渲染 ======
const inject = await ev(`(() => {
  if (typeof ST === 'undefined') return { __err: 'ST undefined' };
  const LONG = 'Qwen/Qwen3-Extremely-Long-Namespace-Organization-Identifier-235B-A22B-Instruct-4bit';
  ST.family = [
    { id: LONG, name: 'Qwen3 超长命名旗舰模型 235B-A22B（视觉+思考）', size_gb: 142.5, note: '长注释文本用于压测描述区换行与卡片高度自适应行为是否正常排列' },
    { id: 'test/short', name: '短名模型', size_gb: 2, note: '' }
  ];
  ST.cache = [{ id: LONG, size_gb: 142.5 }, { id: 'test/short', size_gb: 2 }];
  ST.inst = [{ model: LONG, state: 'ready', port: 8080, params: { context: 32768 } }];
  ST.pulls = {};
  renderCards(); renderCacheList(); renderMetrics({
    instances: ST.inst, metrics_latest: { tps: 88.5, footprint_gb: 107.7, kv: 42, running: 1, waiting: 0 },
    per: { [LONG]: { accepted_ratio: 0.82 } }, mem_free: 96.3, mem_total: 256,
    series: { tps: { values: [1,2,3] }, footprint_gb: { values: [10,20] }, mem_free: { values: [9,8] } }
  });
  $('win-status').textContent = '— 启动中… Qwen3-Extremely-Long-Namespace-Organization-Identifier-235B（长状态文本压测用例）';
  return { ok: true };
})()`);
if (!inject || inject.__err) { console.error('INJECT FAIL', JSON.stringify(inject)); process.exit(1); }

const probe = await ev(`(() => {
  const out = {};
  out.docOverflow = document.documentElement.scrollWidth > window.innerWidth + 1;
  // 模型卡：按钮 vs 卡片右缘
  out.cards = [...document.querySelectorAll('.mcard')].map(card => {
    const cr = card.getBoundingClientRect();
    const row = card.querySelector('.row');
    const rr = row ? row.getBoundingClientRect() : null;
    return {
      cardW: Math.round(cr.width), rowOver: rr ? +(rr.right - cr.right).toFixed(1) : null,
      btns: [...card.querySelectorAll('.row button')].map(b => {
        const br = b.getBoundingClientRect();
        return { t: b.textContent.trim(), w: +br.width.toFixed(1), clippedRight: +(cr.right - br.right).toFixed(1) };
      })
    };
  });
  // 缓存行
  out.pitems = [...document.querySelectorAll('#cache-list .pitem, #inst-list .pitem')].map(p => {
    const pr = p.getBoundingClientRect();
    const mono = p.querySelector('.mono'), right = p.querySelector('.right');
    const delBtn = [...p.querySelectorAll('button')].pop();
    return {
      monoOverRight: right && mono ? +(mono.getBoundingClientRect().right - right.getBoundingClientRect().left).toFixed(1) : null,
      rightOver: right ? +(right.getBoundingClientRect().right - pr.right).toFixed(1) : null,
      delClipped: delBtn ? +(pr.right - delBtn.getBoundingClientRect().right).toFixed(1) : null,
      itemScrollW: p.scrollWidth, itemClientW: p.clientWidth
    };
  });
  // 顶栏侵入
  const wt = document.querySelector('.topbar .wt'), ver = document.querySelector('.ver');
  out.wtRight = wt ? +wt.getBoundingClientRect().right.toFixed(1) : null;
  out.verLeft = ver ? +ver.getBoundingClientRect().left.toFixed(1) : null;
  // 弹窗打开状态
  out.msOpen = $('ms-overlay').classList.contains('open');
  return out;
})()`);

// ====== 判定 ======
ok('文档无横向溢出@900px', !probe.docOverflow, JSON.stringify(probe.docOverflow));

for (const [i, cd] of probe.cards.entries()) {
  const clipped = cd.btns.filter(b => b.w > 0 && (b.clippedRight < -1 || b.w <= 8));
  ok(`模型卡${i}按钮无裁切`, clipped.length === 0 && cd.rowOver <= 1,
    `row溢出=${cd.rowOver} 被裁=[${clipped.map(b => b.t + ':' + b.clippedRight).join(',')}]`);
}
for (const [i, pi] of probe.pitems.entries()) {
  const bad = pi.rightOver > 1 || (pi.delClipped != null && pi.delClipped < -1) || (pi.monoOverRight != null && pi.monoOverRight > 0) || pi.itemScrollW > pi.itemClientW + 1;
  ok(`行${i}无重叠/按钮完整`, !bad, JSON.stringify(pi));
}
const topbarGap = probe.verLeft != null && probe.wtRight != null ? probe.wtRight - probe.verLeft : null;
ok('顶栏状态不侵入版本区', topbarGap != null && topbarGap <= 1, `wt右缘${probe.wtRight} vs ver左缘${probe.verLeft} 差=${topbarGap}`);

// ====== 死按钮：推荐值 ======
openSettingsClick:
{
  const r1 = await ev(`(() => {
    openSettings('test/short');
    $('toast').classList.remove('show');
    return 'opened:' + $('ms-overlay').classList.contains('open');
  })()`);
  await ev(`$('ms-recommend').click(); 'clicked'`);
  const shown = await ev(`!!document.getElementById('toast') && $('toast').classList.contains('show')`);
  ok('推荐值按钮点击有响应', shown === true, `toast显示=${JSON.stringify(shown)}（openSettings=${r1}）`);
  // 弹窗内保存按钮可点性
  const sv = await ev(`(() => {
    const b = $('ms-save'); const r = b.getBoundingClientRect();
    const el = document.elementFromPoint(r.left + r.width/2, r.top + r.height/2);
    return { clickable: el === b || b.contains(el), w: +r.width.toFixed(1) };
  })()`);
  ok('弹窗保存按钮可命中', sv.clickable && sv.w > 10, JSON.stringify(sv));
}

// ====== vtip 溢出检查 ======
const vt = await ev(`(() => {
  const ver = $('win-ver'); ver.classList.add('new');
  const tip = $('win-vtip'); tip.textContent = '引擎有新版本 v9.9.9，设置页一键升级（超长提示文本压测）';
  const tr = tip.getBoundingClientRect();
  return { right: +tr.right.toFixed(1), vw: window.innerWidth, overWindow: tr.right > window.innerWidth };
})()`);
ok('版本提示(vtip)不溢出窗口', !vt.overWindow, `右缘${vt.right} 视口${vt.vw}`);

// ====== 深色主题回归（对比度/重叠常在暗色下暴露）======
const dark = await ev(`(() => {
  document.documentElement.setAttribute('data-theme', 'dark');
  // 模型卡+行仍无裁切
  const cards = [...document.querySelectorAll('.mcard .row')].map(row => {
    const cr = row.closest('.mcard').getBoundingClientRect();
    return [...row.querySelectorAll('button')].every(b => b.getBoundingClientRect().width > 8 && (cr.right - b.getBoundingClientRect().right) >= -1);
  });
  return { allBtnsOk: cards.every(x => x), theme: document.documentElement.getAttribute('data-theme') };
})()`);
ok('深色主题下按钮仍无裁切', dark.allBtnsOk, JSON.stringify(dark));
await ev(`document.documentElement.setAttribute('data-theme', 'light'); 'restored'`);

// ====== 对话页：长会话标题 + 超长模型名 option ======
const chat = await ev(`(() => {
  switchPage('chat');
  ST.chats = [{ id: 'c1', title: '这是一个非常长的会话标题用于测试左栏条目换行或溢出时的表现是否遮挡删除等操作', updated: 1759900000 }];
  ST.cur = { id: 'c1' };
  const sel = $('chat-model');
  sel.innerHTML = '<option value="x">Qwen3-Extremely-Long-Namespace-Organization-Identifier-235B-A22B-Instruct</option>';
  loadChats();
  const convs = [...document.querySelectorAll('.conv')];
  const colW = document.querySelector('.convs').getBoundingClientRect().width;
  return {
    convOverflow: convs.map(cv => { const r = cv.getBoundingClientRect(); return +(r.right - (document.querySelector('.conv-col').getBoundingClientRect().right)).toFixed(1); }),
    anyHoriz: document.querySelector('.convs').scrollWidth > document.querySelector('.convs').clientWidth
  };
})()`);
ok('对话列表长标题不溢出左栏', !chat.anyHoriz && chat.convOverflow.every(x => x <= 1), JSON.stringify(chat));

// ====== 弹窗 frow：label+hint 与 input 同行（120px 定宽）======
const frow = await ev(`(() => {
  openSettings('test/short');
  const rows = [...document.querySelectorAll('#ms-basic .frow')];
  return rows.map(r => {
    const label = r.querySelector('label'), input = r.querySelector('input,select');
    const lr = label.getBoundingClientRect(), ir = input ? input.getBoundingClientRect() : null;
    return {
      text: label.textContent.trim().slice(0, 10),
      labelH: +lr.height.toFixed(1),           // 高度大=换行挤压
      overlap: ir ? +(ir.left - lr.right).toFixed(1) : null  // 负数=重叠
    };
  });
})()`);
const badFrow = frow.filter(f => (f.overlap != null && f.overlap < 0) || f.labelH > 45);
ok('弹窗表单行无重叠/异常换行', badFrow.length === 0, JSON.stringify(badFrow));

console.log(`RESULT: ${pass} PASS / ${fail} FAIL`);
chrome.kill();
srv.close();
process.exit(fail ? 1 : 0);