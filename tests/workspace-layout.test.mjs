import test from 'node:test';
import assert from 'node:assert/strict';
import { readFileSync } from 'node:fs';
import { renderOverview, chooseLaunchModel } from '../web/views/overview.js';
import { renderModels } from '../web/views/models.js';
import { renderActivity } from '../web/views/activity.js';
import { renderWorkspaceSettings } from '../web/views/workspace-settings.js';

globalThis.location ??= { origin:'http://127.0.0.1:43123' };

const source = (path) => readFileSync(new URL(path, import.meta.url), 'utf8');
const model = { id:'/Models/Qwen', name:'Qwen', installed:true, supported:true, startable:true, config:{} };
const state = {
  snapshot:{ engine:{ state:'ready', model:model.id }, update:{ active:{version:'v1'} }, settings:{ selected_model:model.id }, models:[model], stats:{total:{}}, resources:{memory:{}} },
  pageData:{ stats:{total:{requests:3,input_tokens:120,output_tokens:45},requests:[],models:[]}, services:{services:[]}, profiles:{profiles:[]} },
  filters:{statsRange:'24h',statsModel:''},routeQuery:new URLSearchParams(),
};

test('navigation exposes five compact destinations without redundant chrome', () => {
  const html = source('../web/index.html');
  const routes = [...html.matchAll(/class="tf-nav" data-page="([^"]+)"/g)].map((match) => match[1]);
  assert.deepEqual(routes, ['overview','models','activity','settings','chat']);
  assert.doesNotMatch(html, /<aside\b|id="breadcrumbs"|<footer\b/);
  assert.match(html, /id="language-toggle"[^>]*aria-label=/);
  assert.match(html, /id="app-version"/);
  assert.match(source('../web/app.css'), /@media\s*\(max-width:999px\)[^{]*\{[^}]*\.tf-top-nav\s*\{[^}]*overflow-x:auto/);
});

test('legacy routes resolve to owning sections without losing selected model', async () => {
  const { resolveWorkspaceRoute } = await import('../web/workspace-route.js');
  const downloads = resolveWorkspaceRoute('#downloads');
  assert.equal(downloads.page, 'models');
  assert.equal(downloads.query.get('section'), 'downloads');
  const benchmark = resolveWorkspaceRoute('#benchmark');
  assert.equal(benchmark.page, 'activity');
  assert.equal(benchmark.query.get('section'), 'benchmark');
  const selected = resolveWorkspaceRoute('#models?model=%2FModels%2FQwen');
  assert.equal(selected.page, 'models');
  assert.equal(selected.query.get('model'), '/Models/Qwen');
});

test('overview includes compact real usage and model configuration stays on model page', () => {
  const overview = renderOverview(state);
  assert.match(overview, /120/);
  assert.match(overview, /45/);
  assert.match(overview, /3/);
  const models = renderModels(state);
  assert.match(models, /data-form="model-config-save"/);
  assert.match(models, /name="temperature"/);
  assert.doesNotMatch(models, /data-action="model-config-open"/);
});

test('attached model is distinct from default launch target and cannot be stopped here', () => {
  const deepseek = { ...model, id:'/Models/DeepSeek', name:'DeepSeek' };
  const snapshot = { ...state.snapshot, models:[model,deepseek], engine:{state:'attached',model:deepseek.id,control_owner:'external'} };
  const output = renderOverview({ ...state, snapshot });
  assert.match(output, /<h2>\/Models\/DeepSeek<\/h2>/);
  assert.match(output, /data-action="engine-detach"/);
  assert.doesNotMatch(output, /data-action="engine-stop"/);
  assert.match(output, /value="\/Models\/Qwen" selected/);
  assert.equal(chooseLaunchModel(snapshot, deepseek.id).selected, deepseek.id);
  assert.match(renderOverview({ ...state, snapshot, launchTarget:deepseek.id }), /value="\/Models\/DeepSeek" selected/);
});

test('overview shows missing metrics honestly and keeps measured zero', () => {
  const snapshot = { ...state.snapshot, resources:{ memory:{} }, engine:{state:'stopped'} };
  const output = renderOverview({ ...state, snapshot, pageData:{...state.pageData,stats:{total:{requests:0,input_tokens:0,output_tokens:0},requests:[]}} });
  assert.match(output, /未采集/);
  assert.match(output, /请求数<\/div><div class="tf-value">0/);
  assert.match(source('../web/app.js'), /\/api\/stats\?\$\{params\}/);
});

test('request history presents observed Unix time as a readable timestamp', () => {
  const output=renderOverview({...state,pageData:{...state.pageData,stats:{total:{requests:1},requests:[{at:1790768405.85,model:model.id,status:200,input_tokens:2,output_tokens:1,elapsed:0.5}]}}});
  assert.doesNotMatch(output,/1790768405\.85/);
  assert.match(output,/2026/);
});

test('composed sections retain toolbar actions and narrow logs do not force desktop columns', () => {
  const css = source('../web/app.css');
  assert.match(css,/\.tf-composed-section\s*>\s*\.tf-heading:not\(\.has-actions\)\s*\{[^}]*display:none/);
  assert.match(css,/\.tf-composed-section\s*>\s*\.tf-heading\.has-actions\s*>\s*div:first-child\s*\{[^}]*display:none/);
  assert.match(source('../web/views/shared.js'),/tf-heading\$\{actions \? ' has-actions'/);
  assert.match(css,/@media\s*\(max-width:760px\)\s*\{[^}]*\.tf-log-toolbar\s*\{[^}]*grid-template-columns:minmax\(0,1fr\)/);
  assert.match(css,/main\[data-view="chat"\] \.tf-composer \{ position:sticky; bottom:8px/);
});

test('activity and settings keep one page title, local tabs and benchmark safety copy', () => {
  const activity=renderActivity({...state,routeQuery:new URLSearchParams('section=benchmark'),pageData:{...state.pageData,benchmark:{results:[]}}});
  assert.equal((activity.match(/<h1>/g) ?? []).length,1);
  for (const tab of ['activity:logs','activity:benchmark']) assert.match(activity,new RegExp(`data-value="${tab}"`));
  assert.match(activity,/不停止|不会停止|does not stop/);
  const settings=renderWorkspaceSettings({...state,routeQuery:new URLSearchParams('section=runtime'),snapshot:{...state.snapshot,engine:{...state.snapshot.engine,pending:{parallel:2}}}});
  assert.equal((settings.match(/<h1>/g) ?? []).length,1);
  for (const tab of ['runtime','storage','api','updates']) assert.match(settings,new RegExp(`data-value="settings:${tab}"`));
  assert.match(settings,/待重启生效|待应用/);
});

test('workspace typography and focus have readable minimums', () => {
  const css=source('../web/app.css');
  assert.match(css,/body\s*\{[^}]*font:14px/);
  assert.match(css,/\.tf-sub\s*\{[^}]*font-size:12px/);
  assert.match(css,/\.tf-tag[^}]*font-size:12px/);
  assert.match(css,/button:focus-visible/);
  assert.match(css,/main\s*\{[^}]*max-width:1360px/);
  assert.match(css,/\.tf-message-body,\s*\.tf-message-body code[^}]*font-size:14px/);
  assert.match(css,/\.tf-chat-current span,\s*\.tf-message-actions button[^}]*font-size:12px/);
  assert.match(css,/\.tf-chat-metrics,\s*\.tf-code-toolbar[^}]*font-size:12px/);
});
