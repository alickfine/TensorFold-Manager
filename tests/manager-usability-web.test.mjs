import test from 'node:test';
import assert from 'node:assert/strict';

import { formatNumber } from '../web/views/shared.js';
import { catalogDownloadRequest, assertChatCanSubmit, isChatSubmitKey } from '../web/contracts.js';
import { renderDownloads, supportedCatalogEntries } from '../web/views/downloads.js';
import { renderModels } from '../web/views/models.js';
import { renderModelConfigDialog } from '../web/views/model-config.js';
import { renderEngineConfig } from '../web/views/engine-config.js';
import { renderServer } from '../web/views/server.js';
import { renderApi } from '../web/views/api-integration.js';
import { renderUpdates } from '../web/views/updates.js';
import { renderBenchmark, benchmarkRequest } from '../web/views/benchmark.js';
import { renderChat } from '../web/views/chat.js';
import { renderLogs } from '../web/views/logs.js';
import { renderStats } from '../web/views/stats.js';
import { prepareChatTurn } from '../web/chat-options.js';
import { dispatchDocumentClick } from '../web/click-routing.js';

const supported = {
  id:'/Models/Qwen', name:'Qwen', repo:'org/qwen', source:'huggingface',
  installed:true, supported:true, config:{ temperature:0.6 },
};

function state(overrides = {}) {
  return {
    snapshot:{
      settings:{ selected_model:supported.id, engine_port:8089, gateway_port:8080, model_dirs:['/Models'], parallel:'auto', prompt_cache_gib:8, mlx_cache_gib:4 },
      engine:{ state:'ready', model:supported.id, version:'v1' },
      models:[supported], jobs:[], keys:[], profiles:[], capabilities:{ chat:true, streaming:true, benchmark:true },
      update:{ active:{ version:'v1' } }, system:{ hostname:'mac', platform:'darwin' },
    },
    pageData:{
      catalog:{ default_directory:'/Managed', models:[supported], sources:[{ id:'huggingface' }, { id:'modelscope' }] },
      jobs:{ jobs:[] }, credentials:{ providers:{} }, profiles:{ profiles:[] }, keys:{ keys:[] }, updates:{},
      benchmark:{ results:[] }, logs:{ logs:[] },
    },
    routeQuery:new URLSearchParams(), filters:{ logLevel:'', logQuery:'', logLimit:'200' },
    chat:{ options:{}, messages:[], streaming:false },
    ...overrides,
  };
}

test('numeric presentation rounds to at most two decimals without mutating the source value', () => {
  const raw = 12.34567;
  assert.equal(formatNumber(raw), '12.35');
  assert.equal(formatNumber(12.3), '12.3');
  assert.equal(formatNumber(12), '12');
  assert.equal(raw, 12.34567);
});

test('statistics round numeric table values before adding units', () => {
  const current = state();
  const raw = 1.23456;
  current.pageData.stats = {
    total:{ requests:1 },
    models:[{ model:'Qwen', requests:1, avg_elapsed:raw }],
    requests:[{ model:'Qwen', status:200, elapsed:raw, ttft:0.34567, prefill_tps:12.3456, decode_tps:45.6789 }],
  };
  const output = renderStats(current);
  assert.match(output, /1\.23s/);
  assert.match(output, /0\.35s/);
  assert.match(output, /12\.35 tok\/s/);
  assert.match(output, /45\.68 tok\/s/);
  assert.doesNotMatch(output, /1\.23456|0\.34567|12\.3456|45\.6789/);
  assert.equal(raw, 1.23456);
});

test('downloads can only submit a supported official catalog entry using its real repository', () => {
  const catalog = {
    default_directory:'/Managed',
    models:[
      { ...supported, download_sources:['huggingface','hf-mirror'] },
      { repo:'org/qwen-ms', name:'Qwen MS', source:'modelscope', supported:true },
      { repo:'org/unknown', name:'Unknown', source:'huggingface', supported:false },
      { repo:'org/invalid', name:'Invalid', source:'huggingface', download_sources:['unverified-source'], supported:true },
    ],
  };
  assert.deepEqual(supportedCatalogEntries(catalog).map((item) => `${item.source}:${item.repo}`), ['huggingface:org/qwen', 'hf-mirror:org/qwen', 'modelscope:org/qwen-ms']);
  assert.deepEqual(catalogDownloadRequest(catalog, 'huggingface:org/qwen'), {
    path:'/api/downloads', options:{ method:'POST', body:{ repo:'org/qwen', source:'huggingface', revision:'main', directory:'/Managed', use_credentials:false } },
  });
  assert.throws(() => catalogDownloadRequest(catalog, 'huggingface:org/unknown'), /受支持模型|supported model/);
  const output = renderDownloads(state({ pageData:{ ...state().pageData, catalog } }));
  assert.match(output, /<select[^>]+name="catalog_model"/);
  assert.doesNotMatch(output, /<input[^>]+name="repo"|name="revision"|name="directory"/);
  assert.doesNotMatch(output, /org\/unknown|org\/invalid/);
  assert.equal(output.match(/HF 镜像/g)?.length, 2, 'the selector and support table must both identify the mirror source');
  const mixedJobs = [
    { id:'download-1', kind:'download', status:'running', params:{ repo:'jobs/real-download', source:'huggingface' }, progress:{} },
    { id:'probe-1', kind:'model_probe', status:'running' },
    { id:'discover-1', kind:'model_discovery', status:'completed' },
    { id:'install-1', kind:'engine_install', status:'queued' },
    { id:'accuracy-1', kind:'accuracy', status:'failed' },
  ];
  const jobsOutput = renderDownloads(state({ pageData:{ ...state().pageData, catalog, jobs:{ jobs:mixedJobs } } }));
  assert.match(jobsOutput, /jobs\/real-download/);
  assert.doesNotMatch(jobsOutput, /model_probe|model_discovery|engine_install|accuracy-1/);
});

test('model library keeps configuration and model generation fields on one page', () => {
  const current = state();
  const library = renderModels(current);
  assert.match(library, /data-action="model-select" data-value="\/Models\/Qwen"/);
  assert.match(library, /data-form="model-config-save"/);
  assert.doesNotMatch(library, /model-config\?model=/);
  const dialog = renderModelConfigDialog(current, supported.id);
  for (const name of ['context','max_tokens','temperature','top_p','top_k','thinking','drafter','mtp_drafts']) {
    assert.match(dialog, new RegExp(`name="${name}"`));
  }
});

test('model dialog inherits effective global generation values when local overrides are empty', () => {
  const current = state();
  current.snapshot.settings = { ...current.snapshot.settings, temperature:0.42, thinking:true, max_tokens:321 };
  current.snapshot.models = [{ ...supported, config:{} }];
  const dialog = renderModelConfigDialog(current, supported.id);
  assert.match(dialog, /name="temperature"[^>]+value="0\.42"/);
  assert.match(dialog, /name="max_tokens"[^>]+value="321"/);
  assert.match(dialog, /name="thinking"[^>]*>[\s\S]*?<option value="true" selected>/);
});

test('engine configuration contains service resources but no model generation controls', () => {
  const output = renderEngineConfig(state());
  for (const name of ['parallel','prompt_cache_gib','mlx_cache_gib']) assert.match(output, new RegExp(`name="${name}"`));
  for (const name of ['context','max_tokens','temperature','top_p','top_k','thinking','drafter','mtp_drafts','engine_python']) {
    assert.doesNotMatch(output, new RegExp(`name="${name}"`));
  }
  assert.match(output, /运行时|Runtime/);
});

test('server directory discovery reports backend job progress and exposes cancellation', () => {
  const current = state();
  current.snapshot.jobs = [{
    id:'discover-1', kind:'model_discovery', status:'running',
    progress:{ scanned_dirs:17, found:2, phase:'scanning' },
  }];
  const output = renderServer(current);
  assert.match(output, /data-action="models-discover"/);
  assert.match(output, /17/);
  assert.match(output, /2/);
  assert.match(output, /discover-1:cancel/);
  assert.doesNotMatch(output, /name="engine_port"|name="gateway_port"/);
});

test('API page owns both ports and API key lifecycle in one place', () => {
  const current = state();
  current.pageData.keys = { keys:[{ id:'key-1', name:'Client', enabled:true }] };
  const output = renderApi(current);
  assert.match(output, /name="engine_port"/);
  assert.match(output, /name="gateway_port"/);
  assert.match(output, /data-form="key-create"/);
  assert.match(output, /data-action="key-toggle"/);
  assert.match(output, /data-action="key-delete"/);
});

test('API page reports the actually bound gateway separately from pending saved port changes', () => {
  const current = state();
  current.snapshot.settings.gateway_port = 8080;
  current.snapshot.gateway = { port:9090, pending:true, error:'restart required to bind saved port' };
  const output = renderApi(current);
  assert.match(output, /http:\/\/127\.0\.0\.1:9090\/v1/);
  assert.doesNotMatch(output, /http:\/\/127\.0\.0\.1:8080\/v1/);
  assert.match(output, /restart required to bind saved port/);
  assert.match(output, /待重启应用|pending/i);
  current.snapshot.gateway = { port:null, pending:true, error:'bind failed' };
  const failed = renderApi(current);
  assert.doesNotMatch(failed, /http:\/\/127\.0\.0\.1:8080\/v1/);
  assert.match(failed, /bind failed/);
  assert.match(failed, /不可用|unavailable/i);
});

test('disk discovery marks bounded partial results instead of claiming a full disk scan', () => {
  const current = state();
  current.snapshot.jobs = [{
    id:'discover-partial', kind:'model_discovery', status:'completed',
    progress:{ scanned_dirs:32, found:3, phase:'completed' },
    result:{ partial:true, scanned_dirs:32, added_dirs:['/Models/New'], skipped:4, limits:['time_limit'] },
  }];
  const output = renderServer(current);
  assert.match(output, /部分结果|Partial Result/);
  assert.match(output, /180/);
  assert.match(output, /32/);
  assert.match(output, /总数|total/i);
  assert.match(output, /time_limit/);
});

test('updates show backend job failure evidence and gate backend-disallowed actions', () => {
  const current = state();
  current.pageData.updates = {
    active:{ version:'v1' }, staged:{ version:'v2' }, can_activate:false, can_upgrade:false,
    blockers:['api_verification_failed'],
    install_job:{ id:'install-1', status:'failed', error:'wheel validation failed', result:{ log_path:'/safe/update.log' } },
    upgrade_job:{ id:'upgrade-1', status:'failed', progress:{ phase:'smoke_test' }, error:'upgrade smoke test failed' },
    activation_job:{ id:'activate-1', status:'cancelled', error:'user cancelled' },
  };
  const output = renderUpdates(current);
  assert.match(output, /wheel validation failed/);
  assert.match(output, /upgrade smoke test failed/);
  assert.match(output, /api_verification_failed/);
  assert.match(output, /user cancelled/);
  assert.match(output, /data-action="update-activate"[^>]+disabled/);
  assert.match(output, /data-action="update-upgrade"[^>]+disabled/);
});

test('first-use updates page exposes the real engine bootstrap action', () => {
  const current = state();
  current.snapshot.update = { active:null };
  current.pageData.updates = { active:null, can_upgrade:false, blockers:['engine_not_installed'] };
  const output = renderUpdates(current);
  assert.match(output, /data-action="engine-install"/);
  assert.doesNotMatch(output, /data-action="engine-install"[^>]+disabled/);
});

test('benchmark presets submit concrete real request parameters and keep advanced fields collapsed', () => {
  assert.deepEqual(benchmarkRequest('quick', { prompt:'Explain caching', max_tokens:'64', runs:'1' }), {
    prompt:'Explain caching', max_tokens:64, runs:1,
  });
  assert.throws(() => benchmarkRequest('unknown', {}), /测试档位|benchmark tier/);
  const output = renderBenchmark(state());
  assert.match(output, /name="model"/);
  assert.match(output, /name="tier"/);
  assert.match(output, /<details[^>]*class="tf-advanced"/);
  assert.match(output, /data-form="benchmark-run"/);
});

test('chat keeps readable messages above a bottom composer with model and collapsed parameters', () => {
  const current = state();
  current.chat.messages = [{ role:'user', content:'Hello' }, { role:'assistant', content:'Hi' }];
  const output = renderChat(current);
  assert.match(output, /class="tf-chat-toolbar"/);
  assert.match(output, /name="model"/);
  assert.match(output, /data-action="chat-new"/);
  assert.match(output, /<details[^>]*class="tf-chat-parameters"/);
  assert.ok(output.indexOf('id="chat-messages"') < output.indexOf('class="tf-composer"'));
  assert.match(output, /Hello/);
  assert.match(output, /Hi/);
});

test('chat metrics round throughput and elapsed values to at most two decimals', () => {
  const current = state();
  current.chat.messages = [{
    role:'assistant', content:'done', status:'completed',
    metrics:{ elapsed_seconds:1.23456, completion_tokens:10, tokens_per_second:166.937061842322 },
  }];
  const output = renderChat(current);
  assert.match(output, /1\.23s/);
  assert.match(output, /166\.94 tok\/s/);
  assert.doesNotMatch(output, /166\.937061842322|1\.23456/);
});

test('chat submits on plain Enter but preserves Shift+Enter and IME composition', () => {
  assert.equal(isChatSubmitKey({ key:'Enter', shiftKey:false, isComposing:false }), true);
  assert.equal(isChatSubmitKey({ key:'Enter', shiftKey:false, isComposing:false }, { streaming:true }), false);
  assert.equal(isChatSubmitKey({ key:'Enter', shiftKey:true, isComposing:false }), false);
  assert.equal(isChatSubmitKey({ key:'Enter', shiftKey:false, isComposing:true }), false);
  assert.equal(isChatSubmitKey({ key:'a', shiftKey:false, isComposing:false }), false);
  assert.doesNotThrow(() => assertChatCanSubmit(false));
  assert.throws(() => assertChatCanSubmit(true), /生成|generation/);
});

test('invalid chat options do not mutate the conversation and a corrected retry can start', () => {
  const chat = { messages:[{ role:'assistant', content:'ready' }], options:{ temperature:'invalid' } };
  assert.throws(() => prepareChatTurn(chat, 'hello', { top_p:0.9, max_tokens:128 }), /temperature/);
  assert.deepEqual(chat.messages, [{ role:'assistant', content:'ready' }]);
  chat.options.temperature = 0.6;
  const turn = prepareChatTurn(chat, 'hello', { top_p:0.9, max_tokens:128 });
  assert.equal(turn.messages.length, 3);
  assert.equal(turn.assistant.status, 'generating');
  assert.deepEqual(chat.messages, [{ role:'assistant', content:'ready' }]);
});

test('logs use the compact toolbar and log surface classes', () => {
  const output = renderLogs(state());
  assert.match(output, /tf-heading-compact/);
  assert.match(output, /tf-log-toolbar/);
  assert.match(output, /tf-log-card/);
});

test('clicking an action inside main dispatches handleAction instead of treating main as navigation', () => {
  const actionButton = { disabled:false, dataset:{ action:'refresh', value:'now' } };
  const legacyMain = { dataset:{ page:'chat' } };
  const target = {
    closest(selector) {
      if (selector === 'button[data-page]') return null;
      if (selector === '[data-page]') return legacyMain;
      if (selector === '[data-action]') return actionButton;
      return null;
    },
  };
  assert.equal(target.closest('[data-page]'), legacyMain, 'the regression fixture must reproduce the legacy main[data-page] ancestor');
  let navigated = null;
  let handled = null;
  let prevented = false;
  const result = dispatchDocumentClick({ target, preventDefault() { prevented = true; } }, {
    navigate(page) { navigated = page; },
    handleAction(action, value, element) { handled = { action, value, element }; },
  });
  assert.equal(result, 'action');
  assert.equal(navigated, null);
  assert.deepEqual(handled, { action:'refresh', value:'now', element:actionButton });
  assert.equal(prevented, true);
});
