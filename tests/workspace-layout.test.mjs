import test from 'node:test';
import assert from 'node:assert/strict';
import { readFileSync } from 'node:fs';
import { renderOverview } from '../web/views/overview.js';
import { renderModels } from '../web/views/models.js';

globalThis.location ??= { origin:'http://127.0.0.1:43123' };

const source = (path) => readFileSync(new URL(path, import.meta.url), 'utf8');
const model = { id:'/Models/Qwen', name:'Qwen', installed:true, supported:true, startable:true, config:{} };
const state = {
  snapshot:{ engine:{ state:'ready', model:model.id }, update:{ active:{version:'v1'} }, settings:{ selected_model:model.id }, models:[model], stats:{total:{}}, resources:{memory:{}} },
  pageData:{ stats:{total:{requests:3,input_tokens:120,output_tokens:45},requests:[],models:[]}, services:{services:[]}, profiles:{profiles:[]} },
  filters:{statsRange:'24h',statsModel:''},routeQuery:new URLSearchParams(),
};

test('navigation exposes six task pages and legacy routes have canonical owners', () => {
  const html = source('../web/index.html');
  const routes = [...html.matchAll(/class="tf-nav" data-page="([^"]+)"/g)].map((match) => match[1]);
  assert.deepEqual(routes, ['overview','models','downloads','chat','activity','settings']);
  const app = source('../web/app.js');
  assert.match(app, /stats:\s*'overview'/);
  assert.match(app, /cache:\s*'settings'/);
  assert.match(app, /logs:\s*'activity'/);
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

test('composed sections retain toolbar actions and narrow logs do not force desktop columns', () => {
  const css = source('../web/app.css');
  assert.match(css,/\.tf-composed-section\s*>\s*\.tf-heading:not\(\.has-actions\)\s*\{[^}]*display:none/);
  assert.match(css,/\.tf-composed-section\s*>\s*\.tf-heading\.has-actions\s*>\s*div:first-child\s*\{[^}]*display:none/);
  assert.match(source('../web/views/shared.js'),/tf-heading\$\{actions \? ' has-actions'/);
  assert.match(css,/@media\s*\(max-width:760px\)\s*\{[^}]*\.tf-log-toolbar\s*\{[^}]*grid-template-columns:minmax\(0,1fr\)/);
  assert.match(css,/main\[data-view="chat"\] \.tf-composer \{ position:sticky; bottom:8px/);
});
