// 原型↔实现一致性闸门（D3）：ui/index.html 渲染后 DOM 与 prototypes/tfm2.html 逐项对账。
// 用法: node ui_conformance.mjs   （数据经 mock bridge 注入，样式与交互走真实 app.js）
import { spawn } from 'child_process';
import http from 'http';
import fs from 'fs';
import path from 'path';

const ROOT = path.dirname(new URL(import.meta.url).pathname);
const MOCK = fs.readFileSync(path.join(ROOT, 'ui', 'mock_bridge.js'), 'utf-8');

// 内嵌静态服务（& 起的 server 会被回收，必须进程内 listen —— 已两次踩坑）
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
await new Promise(r => srv.listen(8898, '127.0.0.1', r));

const CHROME = '/Applications/Google Chrome.app/Contents/MacOS/Google Chrome';
const PORT = 9334;
const chrome = spawn(CHROME, ['--headless=new', '--no-sandbox', '--disable-gpu',
  '--remote-debugging-port=' + PORT, '--no-first-run', '--no-proxy-server',
  '--user-data-dir=/tmp/tfconf-cdp', 'about:blank'], { stdio: 'ignore' });
await new Promise(r => setTimeout(r, 2000));

function cdp(wsUrl) {
  const ws = new WebSocket(wsUrl); let id = 0; const pend = {};
  return new Promise(res => {
    ws.onopen = () => {
      const api = { send(m, p = {}) { return new Promise(r => { const i = ++id; pend[i] = r; ws.send(JSON.stringify({ id: i, method: m, params: p })); }) } };
      ws.onmessage = e => { const d = JSON.parse(e.data); if (d.id && pend[d.id]) { pend[d.id](d); delete pend[d.id]; } };
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
await c.send('Page.addScriptToEvaluateOnNewDocument', { source: MOCK });
await c.send('Emulation.setDeviceMetricsOverride', { width: 1100, height: 720, deviceScaleFactor: 1, mobile: false });
await c.send('Page.navigate', { url: 'http://127.0.0.1:8898/index.html' });
await new Promise(r => setTimeout(r, 1500));

let pass = 0, fail = 0;
function ok(name, cond, detail) { if (cond) { pass++; console.log('PASS', name); } else { fail++; console.log('FAIL', name, detail || ''); } }
async function ev(expr) {
  const r = await c.send('Runtime.evaluate', { expression: expr, returnByValue: true, awaitPromise: true });
  if (r.exceptionDetails) return { __err: r.exceptionDetails.text };
  return r.result?.result?.value;
}

/* ---------- 导航 ---------- */
let v = await ev(`(()=>{
  const navs=[...document.querySelectorAll('.nav-item')].map(n=>[n.dataset.page,n.textContent.trim()]);
  return JSON.stringify(navs);
})()`);
const navs = JSON.parse(v);
ok('导航四项', navs.length === 4, v);
ok('模型为第一导航', navs[0][0] === 'models' && navs[0][1].includes('模型'), v);
ok('对话在模型之下', navs[1][0] === 'chat');
ok('含监控+设置', navs[2][0] === 'metrics' && navs[3][0] === 'settings');
v = await ev(`document.querySelector('.page.on')?.id`);
ok('默认页=模型', v === 'page-models', v);

/* ---------- 模型卡：与原型同构 ---------- */
v = await ev(`(()=>{
  const cards=[...document.querySelectorAll('#mcards .mcard')];
  return JSON.stringify(cards.map(c=>({
    rid: !!c.querySelector('.rid'),
    ridText: c.querySelector('.rid')?.textContent || '',
    btns: [...c.querySelectorAll('.sbtn')].map(b=>b.textContent.trim()),
    disabledOpacity: [...c.querySelectorAll('.sbtn[disabled]')].map(b=>getComputedStyle(b).opacity),
    active: c.classList.contains('active'),
  })));
})()`);
const cards = JSON.parse(v);
ok('模型卡6张', cards.length === 6, v);
ok('每卡有真实repo id行(rid)', cards.every(c => c.rid && c.ridText.startsWith('TensorFold/')));
ok('每卡三钮(加载|下载/设置/删除)', cards.every(c => c.btns.length === 3
  && ['加载', '↓ 下载'].some(t => c.btns[0] === t) && c.btns[1] === '设置' && ['删除', '取消'].includes(c.btns[2])), v);
ok('禁用钮透明度置灰', cards.flatMap(c => c.disabledOpacity).every(o => parseFloat(o) < 1));

/* ---------- 缓存列表 ---------- */
v = await ev(`document.querySelectorAll('#cache-list .pitem').length>0`);
ok('HF缓存列表有内容', v === true, String(v));

/* ---------- 模型设置弹窗：CLI 提示与原型一致 ---------- */
await ev(`openSettings('TensorFold/Qwen3.8-27B-MLX-4bit')`);
await new Promise(r => setTimeout(r, 300));  // openSettings 异步拉设置后才有数据，等待
v = await ev(`document.getElementById('ms-overlay').classList.contains('open')`);
ok('弹窗可打开', v === true, String(v));
v = await ev(`document.getElementById('ms-title').textContent`);
ok('弹窗标题带模型名', v.includes('Qwen3.8-27B-MLX-4bit'), v);
const hints = ['--context', '--max-tokens', '--temperature', '--top-p', '--thinking', '--reasoning-effort'];
for (const h of hints) {
  v = await ev(`document.getElementById('ms-basic').textContent.includes('${h}')`);
  ok(`基础段CLI提示 ${h}`, v === true, String(v));
}
const advs = ['--parallel', '--mtp-drafts', '--mtp-confidence', '--kv-dtype', '--prompt-cache-gib', '--vision', '--backend'];
for (const h of advs) {
  v = await ev(`document.getElementById('ms-adv').textContent.includes('${h}')`);
  ok(`高级段CLI提示 ${h}`, v === true, String(v));
}
v = await ev(`(()=>{document.querySelector('#ms-overlay .seg2 button:last-child').click();return getComputedStyle(document.getElementById('ms-adv')).display!=='none'})()`);
ok('高级分段可切换', v === true, String(v));
v = await ev(`(()=>{closeSettings();return !document.getElementById('ms-overlay').classList.contains('open')})()`);
ok('弹窗可关闭', v === true, String(v));

/* ---------- 设置页字段 ---------- */
v = await ev(`(()=>{switchPage('settings');return document.getElementById('page-settings').textContent})()`);
for (const kw of ['并发上限', 'Prompt 缓存容量', '自动检查更新', '当前版本', '菜单栏常驻', 'API 端点']) {
  ok(`设置页含「${kw}」`, String(v).includes(kw));
}

/* ---------- 对话页组件 ---------- */
v = await ev(`(()=>{switchPage('chat');return JSON.stringify({
  conv: !!document.querySelector('.conv'),
  sel: !!document.getElementById('chat-model'),
  ta: !!document.getElementById('chat-text'),
  send: !!document.getElementById('btn-send')})})()`);
ok('对话页四组件', JSON.parse(v).conv && JSON.parse(v).sel && JSON.parse(v).ta && JSON.parse(v).send, v);

/* ---------- 监控页组件 ---------- */
v = await ev(`(()=>{switchPage('metrics');return JSON.stringify({
  stats: document.querySelectorAll('#page-metrics .stat').length,
  svg: !!document.querySelector('#chart-tps'),
  bars: document.querySelectorAll('#page-metrics .bars').length})})()`);
const mt = JSON.parse(v);
ok('监控页8卡+曲线+柱图', mt.stats >= 7 && mt.svg && mt.bars >= 3, v);

/* ---------- 对比度（双主题） ---------- */
const cssCheck = `(function(){
  function lum(c){const m=c.match(/[\\d.]+/g).map(Number);const s=m.slice(0,3).map(v=>{v/=255;return v<=0.03928?v/12.92:Math.pow((v+0.055)/1.055,2.4)});return 0.2126*s[0]+0.7152*s[1]+0.0722*s[2]}
  function effBg(el){let e=el;while(e){const b=getComputedStyle(e).backgroundColor;if(b&&!/rgba\\(0, 0, 0, 0\\)|transparent/.test(b))return b;e=e.parentElement}return getComputedStyle(document.body).backgroundColor}
  function rows(){const out=[];for(const sel of ['.nav-item','.nav-item.on','.mcard .rid','.mcard .desc','.sbtn','.setrow .sl b','.chip','.badge.run','.stat .lb','.stat .sub','.ver','.foot']){
    const el=document.querySelector(sel);if(!el)continue;
    const fg=getComputedStyle(el).color,bg=effBg(el);
    const cr=(Math.max(lum(fg),lum(bg))+0.05)/(Math.min(lum(fg),lum(bg))+0.05);
    out.push([sel,Math.round(cr*100)/100,fg,bg])}return out}
  return JSON.stringify(rows())
})()`;
for (const theme of ['light', 'dark']) {
  await ev(`document.documentElement.setAttribute('data-theme','${theme}')`);
  await new Promise(r => setTimeout(r, 100));
  const rows = JSON.parse(await ev(cssCheck));
  const bad = rows.filter(r => r[1] < 4.5);
  ok(`对比度≥4.5 (${theme})`, bad.length === 0, JSON.stringify(bad));
}

/* ---------- 布局无横向溢出 ---------- */
await ev(`document.documentElement.setAttribute('data-theme','light');switchPage('models')`);
await new Promise(r => setTimeout(r, 300));
v = await ev(`document.documentElement.scrollWidth<=document.documentElement.clientWidth`);
ok('1100px 无横向溢出', v === true, String(v));

console.log(`\nRESULT: ${pass} PASS / ${fail} FAIL`);
chrome.kill(); srv.close();
process.exit(fail ? 1 : 0);
