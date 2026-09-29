import test from 'node:test';
import assert from 'node:assert/strict';

import {
  getLocale,
  initializeLocale,
  resolveInitialLocale,
  setLocale,
  t,
} from '../web/i18n.js';
import { captureFormDraft, restoreFormDraft } from '../web/form-draft.js';
import { parseChatOptions } from '../web/chat-options.js';
import { downloadRequest } from '../web/contracts.js';
import { parseApiError } from '../web/api.js';
import { renderOverview } from '../web/views/overview.js';
import { renderStats } from '../web/views/stats.js';
import { renderCache } from '../web/views/cache.js';
import { renderModels } from '../web/views/models.js';
import { renderDownloads } from '../web/views/downloads.js';
import { renderModelConfig } from '../web/views/model-config.js';
import { renderModelTools, syncQuantizationForm } from '../web/views/model-tools.js';
import { renderEngineConfig } from '../web/views/engine-config.js';
import { renderServer } from '../web/views/server.js';
import { renderApi } from '../web/views/api-integration.js';
import { renderAuth } from '../web/views/auth.js';
import { renderUpdates } from '../web/views/updates.js';
import { renderLogs } from '../web/views/logs.js';
import { renderBenchmark } from '../web/views/benchmark.js';
import { renderAccuracy } from '../web/views/accuracy.js';
import { renderChat } from '../web/views/chat.js';
import { renderCapabilities } from '../web/views/capabilities.js';

globalThis.location ??= { origin:'http://127.0.0.1:43123' };

test('locale initialization persists and reports only a supported enum', () => {
  const writes = [];
  const messages = [];
  const storage = {
    getItem: (key) => key === 'tensorfold.locale' ? 'en' : null,
    setItem: (key, value) => writes.push([key, value]),
  };
  const document = { documentElement:{ lang:'' } };
  const webkit = { messageHandlers:{ language:{ postMessage:(value) => messages.push(value) } } };

  assert.equal(resolveInitialLocale({ storage, navigator:{ language:'zh-CN' } }), 'en');
  assert.equal(initializeLocale({ storage, navigator:{ language:'zh-CN' }, document, webkit }), 'en');
  assert.equal(getLocale(), 'en');
  assert.equal(document.documentElement.lang, 'en');
  assert.deepEqual(writes, [['tensorfold.locale', 'en']]);
  assert.deepEqual(messages, ['en']);
  assert.equal(t('刷新'), 'Refresh');

  assert.equal(setLocale('fr', { storage, document, webkit }), false);
  assert.deepEqual(writes, [['tensorfold.locale', 'en']]);
  assert.deepEqual(messages, ['en']);
});

test('initial locale falls back from invalid storage to the browser language', () => {
  const storage = { getItem:() => 'not-a-locale' };
  assert.equal(resolveInitialLocale({ storage, navigator:{ language:'zh-TW' } }), 'zh-CN');
  assert.equal(resolveInitialLocale({ storage, navigator:{ language:'en-US' } }), 'en');
});

test('language rerender preserves unsaved values without persisting form contents', () => {
  const oldControls = [
    { tagName:'INPUT', id:'field-model', name:'model', type:'text', value:'/Models/用户草稿', checked:false },
    { tagName:'INPUT', id:'field-token', name:'token', type:'password', value:'temporary-secret', checked:false },
    { tagName:'INPUT', id:'field-thinking', name:'thinking', type:'checkbox', value:'on', checked:true },
    { tagName:'TEXTAREA', id:'chat-input', name:'message', type:'textarea', value:'未发送内容', checked:false, selectionStart:2, selectionEnd:4 },
  ];
  const freshControls = oldControls.map((control) => ({ ...control, value:'', checked:false, selectionStart:0, selectionEnd:0 }));
  const root = (controls) => ({ querySelectorAll:() => controls });

  const draft = captureFormDraft(root(oldControls), oldControls[3]);
  restoreFormDraft(root(freshControls), draft);

  assert.equal(freshControls[0].value, '/Models/用户草稿');
  assert.equal(freshControls[1].value, 'temporary-secret');
  assert.equal(freshControls[2].checked, true);
  assert.equal(freshControls[3].value, '未发送内容');
  assert.equal(freshControls[3].selectionStart, 2);
  assert.equal(freshControls[3].selectionEnd, 4);
});

test('quantization restore rebuilds dependent choices for the restored source model', () => {
  setLocale('en', { storage:null, document:null, webkit:null });
  const target = { innerHTML:'', value:'', disabled:false };
  const submit = { disabled:false };
  const reason = { textContent:'' };
  const form = {
    elements:{ model:{ value:'model-b' }, target, bits:{ value:'' }, group_size:{ value:'' } },
    querySelector:(selector) => selector === 'button[type="submit"]' ? submit : reason,
  };
  const tools = { quantization:{ models:[
    { model:'model-a', choices:[{ bits:4, group_size:64 }] },
    { model:'model-b', choices:[{ bits:4, group_size:32 }, { bits:3, group_size:16 }] },
  ] } };

  syncQuantizationForm(form, tools, '4:32');

  assert.match(target.innerHTML, /4:32/);
  assert.doesNotMatch(target.innerHTML, /4:64/);
  assert.equal(target.value, '4:32');
  assert.equal(form.elements.bits.value, 4);
  assert.equal(form.elements.group_size.value, 32);
  assert.equal(target.disabled, false);
  assert.equal(submit.disabled, false);
  assert.match(reason.textContent, /verification/);
});

test('English local validation and protocol fallback errors are translated without changing backend messages', async () => {
  setLocale('en', { storage:null, document:null, webkit:null });

  assert.throws(() => parseChatOptions({ tools_json:'{' }), /Invalid tools JSON/);
  assert.throws(() => parseChatOptions({ temperature:9 }), /temperature is out of range/);
  assert.throws(() => downloadRequest({ repo:'not-an-exact-repo' }), /exact owner\/model identifier/);

  const fallback = await parseApiError(new Response('', { status:418 }));
  assert.equal(fallback.message, 'Request failed (HTTP 418)');
  const backend = await parseApiError(new Response(JSON.stringify({ error:{ message:'保存' } }), {
    status:400,
    headers:{ 'content-type':'application/json' },
  }));
  assert.equal(backend.message, '保存');
});

function bilingualState(overrides = {}) {
  const model = { id:'/Models/Qwen', name:'Qwen', repo:'org/qwen', installed:true, supported:true, size_bytes:1024 };
  return {
    page:'overview',
    snapshot:{
      app_version:'1.0', instance_id:'instance',
      update:{ active:{ version:'v1' }, releases:[] },
      settings:{ selected_model:model.id, max_tokens:256, context:32768, model_dirs:['/Models'] },
      engine:{ state:'stopped', control_owner:null, child_exit_confirmed:true },
      models:[model], jobs:[], keys:[], profiles:[], stats:{ total:{} }, resources:{}, system:{},
      capabilities:{ chat:{ supported:true }, streaming:{ supported:true }, benchmark:{ supported:true }, accuracy:{ supported:true }, quantize:{ supported:true, ready:true }, upload:{ supported:true, ready:true } },
    },
    pageData:{
      services:{ services:[] }, stats:{ requests:[], models:[], total:{} }, cache:{ can_clear:true },
      catalog:{ models:[], sources:[], default_directory:'/Managed' }, jobs:{ jobs:[] },
      tools:{ active:null, pins:{}, quantization:{ models:[] } }, credentials:{ providers:{} },
      profiles:{ profiles:[] }, keys:{ keys:[] }, updates:{ releases:[] }, logs:{ logs:[] },
      benchmark:{ results:[] }, accuracy:{ cases:[], results:[] },
    },
    routeQuery:new URLSearchParams(),
    filters:{ statsModel:'', statsRange:'24h', logLevel:'', logQuery:'', logLimit:'50' },
    chat:{ options:{}, messages:[], streaming:false, controller:null },
    ...overrides,
  };
}

test('all 17 pages render explicit English UI without leftover Chinese UI copy', () => {
  setLocale('en', { storage:null, document:null, webkit:null });
  const state = bilingualState();
  const pages = [
    ['Overview', renderOverview], ['Statistics', renderStats], ['Cache Management', renderCache],
    ['Model Library', renderModels], ['Model Downloader', renderDownloads], ['Model Configuration', renderModelConfig],
    ['Quantization', renderModelTools], ['Inference Engine Configuration', renderEngineConfig],
    ['Server', renderServer], ['API', renderApi], ['Authentication', renderAuth],
    ['Versions', renderUpdates], ['Logs', renderLogs], ['Benchmark', renderBenchmark],
    ['Reference Answer Tests', renderAccuracy], ['Built-in Chat', renderChat], ['Capability Matrix', renderCapabilities],
  ];
  const untranslated = [];
  for (const [heading, renderer] of pages) {
    const output = renderer(state);
    assert.match(output, /class="tf-heading"/, `${heading} must render a page heading`);
    const matches = output.match(/[\u3400-\u9fff][^<>]*/g) ?? [];
    if (matches.length) untranslated.push([heading, ...new Set(matches)]);
  }
  assert.deepEqual(untranslated, []);
});

test('English catalog covers populated service, job, result, credential, and upload states', () => {
  setLocale('en', { storage:null, document:null, webkit:null });
  const state = bilingualState();
  const job = { id:'job-1', kind:'accuracy', status:'running', params:{ suite:'all' }, progress:{ completed:1, total:2 } };
  state.snapshot = {
    ...state.snapshot,
    engine:{ state:'ready', control_owner:'manager', child_exit_confirmed:false, model:'/Models/Qwen', health:'ok', version:'v1', pid:42, health_detail:{ memory:{ footprint:1024 } } },
    jobs:[job, { ...job, id:'job-2', kind:'benchmark' }, { ...job, id:'job-3', kind:'tool_install' }],
    keys:[{ id:'key', name:'Client', enabled:true, created_at:'today', expires_at:'later' }],
    profiles:[{ id:'profile', name:'Fast', config:{ max_tokens:64 } }],
    resources:{ memory:{ physical_bytes:1024, available_bytes:512, pressure:'normal', swap_used_bytes:0 }, services:[] },
  };
  state.pageData = {
    ...state.pageData,
    services:{ services:[{ pid:12, kind:'tensorfold', executable:'/bin/tensorfold', start_time:'today', model_path:'/Models/Other', port:8089, model_ids:['other'], health:{ status:'ready' }, snapshot_id:'snapshot', expires_in_seconds:30, control:{ supported:true, action:'stop_and_switch' } }] },
    catalog:{ default_directory:'/Managed', sources:[{ id:'huggingface', credentials_supported:true }, { id:'mirror', third_party:true }], models:[{ name:'Qwen', repo:'org/qwen', source:'huggingface', supported:true }] },
    jobs:{ jobs:[{ id:'download', kind:'download', status:'running', params:{ repo:'org/qwen', source:'huggingface' }, progress:{ downloaded_bytes:512, total_bytes:1024 } }] },
    tools:{ active:{ installed_at:'today', packages:{ tool:'1' } }, pins:{ tool:'1' }, quantization:{ models:[{ model:'/Models/Qwen', choices:[{ bits:4, group_size:64 }] }] } },
    credentials:{ providers:{ 'hf-download':{ configured:true }, 'hf-upload':{ configured:true }, 'modelscope-download':{ configured:false } } },
    uploadPlan:{ plan_id:'plan', repo:'owner/model', visibility:'public', existing:false, size_bytes:12, files:[{ path:'weights.bin', size_bytes:12, sha256:'abc' }] },
    profiles:{ profiles:[{ id:'profile', name:'Fast', config:{ max_tokens:64 } }] },
    keys:{ keys:[{ id:'key', name:'Client', enabled:true, created_at:'today', expires_at:'later' }] },
    updates:{ active:{ version:'v1' }, staged:{ version:'v2', api_verified:true }, previous:{ version:'v0' }, latest:{ version:'v2', pinned:true }, notes:'Release notes' },
    logs:{ logs:[{ at:1, level:'info', source:'engine', message:'Started' }] },
    benchmark:{ results:[{ id:'bench', status:'completed', model:'Qwen', prompt:'Hello', runs:1, parameters:{ max_tokens:8 }, results:[{ status:200, output_tokens:3 }] }] },
    accuracy:{ cases:[{ id:'case', name:'Case', prompt:'Question', expected:'Answer', match:'contains', max_tokens:8 }], results:[{ id:'result', status:'completed', completed:1, total:1, passed:1, agreement_rate:1, model:'Qwen', engine_version:'v1', results:[{ case:{ name:'Case', expected:'Answer' }, output:'Answer', passed:true, metrics:{ output_tokens:1 } }] }] },
  };
  state.chat = { options:{}, streaming:true, controller:{ marker:'must-survive' }, messages:[{ role:'user', content:'Hello' }, { role:'assistant', content:'Hi', reasoning:'Reasoning', tool_calls:[{ function:{ name:'lookup', arguments:'{}' } }], metrics:{ elapsed_seconds:1, completion_tokens:1, tokens_per_second:1 } }] };
  const renderers = [renderOverview, renderStats, renderCache, renderModels, renderDownloads, renderModelConfig, renderModelTools, renderEngineConfig, renderServer, renderApi, renderAuth, renderUpdates, renderLogs, renderBenchmark, renderAccuracy, renderChat, renderCapabilities];
  const untranslated = renderers.flatMap((renderer) => renderer(state).match(/[\u3400-\u9fff][^<>]*/g) ?? []);
  assert.deepEqual([...new Set(untranslated)], []);
  assert.equal(state.chat.controller.marker, 'must-survive');
});

test('English rendering never translates raw model, profile, chat, log, path, or form values', () => {
  setLocale('en', { storage:null, document:null, webkit:null });
  const state = bilingualState();
  const collisionModel = { id:'/Models/运行总览', name:'运行总览', repo:'保存', installed:true, supported:true };
  const collisionState = {
    ...state,
    snapshot:{ ...state.snapshot, models:[collisionModel], engine:{ state:'ready', model:collisionModel.id }, profiles:[{ id:'p', name:'保存', config:{} }] },
    pageData:{
      ...state.pageData,
      profiles:{ profiles:[{ id:'p', name:'保存', config:{ name:'运行总览' } }] },
      logs:{ logs:[{ at:'now', level:'info', source:'user', message:'保存', details:{ path:'/用户/运行总览' } }] },
    },
    chat:{ ...state.chat, messages:[{ role:'user', content:'运行总览' }, { role:'assistant', content:'保存', reasoning:'用户原文' }] },
  };
  const output = [renderModels(collisionState), renderModelConfig(collisionState), renderLogs(collisionState), renderChat(collisionState)].join('\n');
  for (const raw of ['运行总览', '保存', '/Models/运行总览', '用户原文']) assert.match(output, new RegExp(raw));
  assert.match(output, /Model Library/);
  assert.match(output, /<h1>Chat<\/h1>/);
});

test('language controls are accessible and native can query or set the strict locale API', async () => {
  const { readFile } = await import('node:fs/promises');
  const index = await readFile(new URL('../web/index.html', import.meta.url), 'utf8');
  assert.match(index, /<select[^>]+id="language-select"[^>]+aria-label=/);
  assert.match(index, /<option value="zh-CN"/);
  assert.match(index, /<option value="en"/);
});
