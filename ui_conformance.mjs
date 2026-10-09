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
ok('监控为第一导航', navs[0][0] === 'metrics' && navs[0][1].includes('监控'), v);
ok('第二项模型', navs[1][0] === 'models' && navs[1][1].includes('模型'));
ok('第三对话+第四设置', navs[2][0] === 'chat' && navs[3][0] === 'settings');
v = await ev(`document.querySelector('.page.on')?.id`);
ok('默认页=监控', v === 'page-metrics', v);

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
// 2026-10-09：模型 id 展示不带提供者（TensorFold/），完整 ref 保留在 title 里
ok('每卡有 id 行且不带 provider 前缀', cards.every(c => c.rid && !c.ridText.includes('/')), v);
ok('每卡三钮(加载|下载/设置/删除)', cards.every(c => c.btns.length === 3
  && ['加载', '↓ 下载'].some(t => c.btns[0] === t) && c.btns[1] === '设置' && ['删除', '取消'].includes(c.btns[2])), v);
ok('禁用钮透明度置灰', cards.flatMap(c => c.disabledOpacity).every(o => parseFloat(o) < 1));

/* ---------- 模型卡 ↔ 辅助模型联动（2026-10-09：草稿模型要能一眼看到并点进去配） ---------- */
v = await ev(`(()=>{
  const c=[...document.querySelectorAll('#mcards .mcard')].find(x=>x.textContent.includes('Qwen3.8-27B (4bit)'));
  const ch=c && c.querySelector('.accelchip');
  return JSON.stringify({has:!!ch, cls:ch?ch.className:'', txt:ch?ch.textContent:'', once:ch?!!ch.getAttribute('onclick'):false});
})()`);
{
  const d = JSON.parse(v);
  ok('模型卡有加速 chip', d.has === true, v);
  ok('加速 chip 报已就绪并带模型名', d.cls.includes('on') && d.txt.includes('已就绪') && d.txt.includes('Qwen3.8-27B-DFlash2'), v);
  ok('加速 chip 非按钮（不破坏卡上三钮约束）', await ev(`(()=>{const c=[...document.querySelectorAll('#mcards .mcard')].find(x=>x.textContent.includes('Qwen3.8-27B (4bit)'));const ch=c.querySelector('.accelchip');return !!ch && !ch.classList.contains('sbtn')})()`) === true);
  ok('加速 chip 点了进该模型设置', d.once === true, v);
}

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

/* ---------- 模型属性区与默认值（2026-10-09 老板四项要求） ---------- */
v = await ev(`(()=>{
  const ats=[...document.querySelectorAll('#ms-attrs .at')].map(e=>e.textContent);
  return JSON.stringify({n:ats.length, text:ats.join('|')});
})()`);
{
  const d = JSON.parse(v);
  ok('属性区有徽标', d.n >= 4, v);
  ok('属性区标出支持图像', d.text.includes('支持图像'));
  ok('属性区标出内置 MTP', d.text.includes('MTP'));
  ok('属性区标出加速配套草稿模型', d.text.includes('草稿模型'));
  ok('属性区标出输入上限', d.text.includes('输入上限'));
}
// 初始值取模型默认（mock 的 config: max_position_embeddings=262144），不是写死的 32768
v = await ev(`document.getElementById('ms-context').value`);
ok('上下文初值=模型默认(262144)', String(v) === '262144', String(v));
v = await ev(`document.getElementById('ms-ctx-hint').textContent.includes('输入上限')`);
ok('上下文提示标注输入上限', v === true, String(v));
v = await ev(`document.getElementById('ms-maxtok-hint').textContent.includes('输出上限')`);
ok('输出提示标注输出上限', v === true, String(v));
// 模型支持图像 → 视觉开关可用（非 disabled）
v = await ev(`!document.getElementById('ms-vision').classList.contains('disabled')`);
ok('支持图像的模型视觉开关可用', v === true, String(v));
/* ---------- 加速配套区块：草稿模型从「只读徽标」升级为「可配置」（2026-10-09） ---------- */
v = await ev(`(()=>{
  const b=document.getElementById('ms-accel');
  return JSON.stringify({disp:getComputedStyle(b).display!=='none', txt:b.textContent});
})()`);
{
  const d = JSON.parse(v);
  ok('设置弹窗有加速配套区块', d.disp === true, v);
  ok('加速区块显示草稿模型全名', d.txt.includes('z-lab/Qwen3.8-27B-DFlash2'), v);
  ok('加速区块显示已下载与体积', d.txt.includes('已下载') && /\d+ GB/.test(d.txt), v);
  ok('加速区块标注 --no-drafts 口径', d.txt.includes('--no-drafts'), v);
}
ok('推测解码开关存在且默认开', await ev(`(()=>{const el=document.getElementById('ms-drafts');return !!el && el.classList.contains('on')})()`) === true);
ok('推测解码开关可点击切换', await ev(`(()=>{const el=document.getElementById('ms-drafts');el.click();const off=!el.classList.contains('on');el.click();return off&&el.classList.contains('on')})()`) === true);
// 回归防护：这两个开关此前根本没绑点击处理（点上去毫无反应）
ok('思考模式开关已绑点击', await ev(`(()=>{const el=document.getElementById('ms-thinking');const was=el.classList.contains('on');el.click();const f=el.classList.contains('on')!==was;el.click();return f})()`) === true);
ok('视觉开关已绑点击', await ev(`(()=>{const el=document.getElementById('ms-vision');const was=el.classList.contains('on');el.click();const f=el.classList.contains('on')!==was;el.click();return f})()`) === true);
// 保存必须把开关落成 drafts 参数（对应引擎 --no-drafts）
await ev(`(()=>{const el=document.getElementById('ms-drafts');if(!el.classList.contains('on'))el.click();document.getElementById('ms-save').click()})()`);
await new Promise(r => setTimeout(r, 400));
v = await ev(`(window.__lastSave||{}).params && window.__lastSave.params.drafts`);
ok('保存上报 drafts 参数', v === true, String(v));

v = await ev(`(()=>{closeSettings();return !document.getElementById('ms-overlay').classList.contains('open')})()`);
ok('弹窗可关闭', v === true, String(v));

/* ---------- 设置页字段 ---------- */
v = await ev(`(()=>{switchPage('settings');return document.getElementById('page-settings').textContent})()`);
for (const kw of ['并发上限', 'Prompt 缓存容量', '自动检查更新', '当前版本', '菜单栏常驻', 'API 端点',
                  '模型目录', '添加自定义目录']) {
  ok(`设置页含「${kw}」`, String(v).includes(kw));
}

/* ---------- 模型目录（扫描根）：mock 注入 oMLX/自定义，断言渲染与去重 ---------- */
v = await ev(`(()=>{
  const rows=[...document.querySelectorAll('#scan-roots .pitem')].map(el=>el.textContent);
  return JSON.stringify({n:rows.length, text:rows.join('|')});
})()`);
{
  const d = JSON.parse(v);
  ok('模型目录列出 4 个内置根', d.n === 6, `${d.n} 行（5 根 + 合计行）`);
  ok('模型目录含 oMLX 根', d.text.includes('oMLX'));
  ok('模型目录含 MTPLX 根', d.text.includes('MTPLX'));
  ok('自定义目录有「移除」按钮', await ev(`(()=>!!document.querySelector('#scan-roots .sbtn.del'))()`) === true);
  ok('内置目录标「内置」不可删', String(d.text).includes('内置'));
}

/* ---------- 本机模型列表：外部目录模型带来源标签且不可删 ---------- */
v = await ev(`(()=>{
  const rows=[...document.querySelectorAll('#cache-list .pitem')].map(el=>el.textContent);
  return JSON.stringify(rows);
})()`);
{
  const rows = JSON.parse(v);
  ok('本机模型含 oMLX 来源条目', rows.some(r => r.includes('oMLX') && r.includes('GLM-5.3-Flash-MLX-4bit-MTP')));
  ok('外部目录模型不给删除按钮（显示"外部"）', rows.some(r => r.includes('外部')));
  ok('HF 模型仍可删', await ev(`(()=>[...document.querySelectorAll('#cache-list .pitem')].some(el=>el.textContent.includes('Qwen3.8-27B-MLX-4bit')&&!!el.querySelector('.sbtn.del')))()`) === true);
  // 2026-10-09：列表展示名去 provider（不出现 TensorFold/ 前缀）；非官方模型给「开启」入口
  ok('缓存列表展示名不带 provider', !rows.some(r => r.includes('TensorFold/')));
  ok('非官方模型有「开启」按钮', await ev(`(()=>[...document.querySelectorAll('#cache-list .pitem')].some(el=>el.textContent.includes('非官方')&&[...el.querySelectorAll('.sbtn')].some(b=>b.textContent.trim()==='开启')))()`) === true);
  /* ---------- 辅助（草稿）模型：不给「开启」，要联到主模型（2026-10-09） ---------- */
  const draftRow = `[...document.querySelectorAll('#cache-list .pitem')].find(e=>e.textContent.includes('Qwen3.8-27B-DFlash2'))`;
  ok('缓存列表把草稿标成「辅助模型」', rows.some(r => r.includes('辅助模型') && r.includes('Qwen3.8-27B-DFlash2')), rows.join('|'));
  ok('辅助模型不给「开启」（不能当主模型加载）', await ev(`(()=>{const el=${draftRow};return !!el && ![...el.querySelectorAll('.sbtn')].some(b=>b.textContent.trim()==='开启')})()`) === true);
  ok('辅助模型联到主模型设置', await ev(`(()=>{const el=${draftRow};const b=el&&[...el.querySelectorAll('.sbtn')].find(x=>x.textContent.includes('用于'));return !!b && String(b.getAttribute('onclick')).includes('openSettings')})()`) === true);

  /* ---------- 草稿模型未下载分支：卡片改口径 + 弹窗给下载入口 ---------- */
  await ev(`(()=>{window.__mock.draftCached=false;return renderModelsPage()})()`);
  await new Promise(r => setTimeout(r, 400));
  v = await ev(`(()=>{const c=[...document.querySelectorAll('#mcards .mcard')].find(x=>x.textContent.includes('Qwen3.8-27B (4bit)'));const ch=c.querySelector('.accelchip');return ch?ch.textContent:''})()`);
  ok('草稿未下载时卡片改口径', String(v).includes('未下载'), v);
  await ev(`openSettings('TensorFold/Qwen3.8-27B-MLX-4bit')`);
  await new Promise(r => setTimeout(r, 350));
  v = await ev(`(()=>{const b=document.getElementById('ms-accel');return JSON.stringify({txt:b.textContent,btn:!!b.querySelector('.sbtn')})})()`);
  {
    const d = JSON.parse(v);
    ok('未下载时加速区块出现下载按钮', d.btn === true, v);
    ok('未下载时给出 pull 命令', d.txt.includes('tensorfold pull z-lab/Qwen3.8-27B-DFlash2'), v);
  }
  await ev(`closeSettings()`);
  await ev(`(()=>{window.__mock.draftCached=true;return renderModelsPage()})()`);
  await new Promise(r => setTimeout(r, 300));
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
ok("监控页分区+曲线+柱图", mt.stats >= 7 && mt.svg && mt.bars >= 3, v);

/* ---------- 监控页：空态文案 + 读数整数化（2026-10-09 用户反馈） ---------- */
// 缺陷1「暂无吞吐数据字体变形」：chart-tps 是 preserveAspectRatio="none" 的拉伸坐标系，
// 文案若写在 <svg><text> 里会被横向压扁 → 必须走 HTML 覆盖层。
const chart = await ev(`(()=>{
  renderMetrics({ mem_total: 256, mem_free: 170.2,
    metrics_latest: { tps: 8.4, prefill_tps: 2431.7, footprint_gb: 107.7, kv: 62.4,
                      running: 1, waiting: 0, prompt_tokens: 12345, gen_tokens_total: 6789,
                      requests_done: 12, cpu_percent: 33.4, gpu_percent: 12.6 },
    per: { 'mock/m': { kv: 62.4, accepted_ratio: 0.7273 } }, series: {} });
  const ov = document.getElementById('chart-tps-empty');
  return JSON.stringify({
    hasOverlay: !!ov, text: ov ? ov.textContent.trim() : '',
    shown: ov ? getComputedStyle(ov).display !== 'none' : false,
    textInSvg: document.querySelectorAll('#chart-tps text').length,
    readouts: ['st-tps','st-prefill','st-mem','st-free','st-kv','st-mtp','st-cache-eff',
               'st-cpu','st-gpu','st-hostmem'].map(i => (document.getElementById(i)||{}).textContent || ''),
  })})()`);
const ch = JSON.parse(chart);
ok("空态文案在 HTML 覆盖层（不在被拉伸的 SVG 内）",
   ch.hasOverlay && ch.textInSvg === 0 && /暂无吞吐数据/.test(ch.text), chart);
ok("空态覆盖层可见", ch.shown, chart);
ok("监控读数无小数（0 位）", ch.readouts.every(t => !/\d\.\d/.test(t)), JSON.stringify(ch.readouts));
// 有数据时覆盖层应隐藏、改由 SVG polyline 呈现
const chartOn = await ev(`(()=>{
  renderMetrics({ mem_total: 256, mem_free: 190, metrics_latest: { tps: 8 },
    per: {}, series: { tps: { values: [1,5,9,3,8] } } });
  const ov = document.getElementById('chart-tps-empty');
  return JSON.stringify({ shown: getComputedStyle(ov).display !== 'none',
    poly: document.querySelectorAll('#chart-tps polyline').length,
    textInSvg: document.querySelectorAll('#chart-tps text').length })})()`);
const chOn = JSON.parse(chartOn);
ok("有吞吐数据时隐藏空态并画曲线",
   !chOn.shown && chOn.poly === 1 && chOn.textInSvg === 0, chartOn);
// 版本信息必须启动即加载（旧版只在打开设置页时取 settings，监控页长期显示 "App v— · 引擎 未安装"）
const verTxt = await ev(`JSON.stringify({
  win: (document.getElementById('win-ver')||{}).textContent || '',
  host: (document.getElementById('host-versions')||{}).textContent || '' })`);
const vj = JSON.parse(verTxt);
ok("顶栏版本取自后端（不是写死的回退值）", /v2\.0\.0/.test(vj.win), verTxt);
ok("监控页「软件版本」行已填充", /App v2\.0\.0/.test(vj.host) && /引擎 0\.6\.4/.test(vj.host), verTxt);
// 版本晚到也必须能回填：settings 含 pool.detect()，冷启动可能很慢或压根不返回，
// 因此 boot 不得 await 它（曾把整个 boot 挂死，导致 2.5s 轮询都没注册上）。
const late = await ev(`(async () => {
  switchPage('metrics');
  ST.settings = {};
  document.getElementById('win-ver').childNodes[0].nodeValue = 'v—';
  await loadVersions();
  return JSON.stringify({ win: document.getElementById('win-ver').textContent,
                          host: document.getElementById('host-versions').textContent });
})()`);
const lj = JSON.parse(late);
ok("版本晚到也能回填顶栏与监控页版本行",
   /v2\.0\.0/.test(lj.win) && /App v2\.0\.0/.test(lj.host), late);

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
