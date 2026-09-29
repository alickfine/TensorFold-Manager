import test from 'node:test';
import assert from 'node:assert/strict';

import { renderOverview } from '../web/views/overview.js';
import { renderChat } from '../web/views/chat.js';
import { renderBenchmark } from '../web/views/benchmark.js';
import * as downloadsView from '../web/views/downloads.js';
import { renderEngineConfig } from '../web/views/engine-config.js';
import { renderStats } from '../web/views/stats.js';
import { renderCache } from '../web/views/cache.js';
import { serializeSettings } from '../web/views/settings.js';
import { readFileSync } from 'node:fs';
import { renderModels } from '../web/views/models.js';
import { renderModelConfigDialog } from '../web/views/model-config.js';
import { renderServer } from '../web/views/server.js';
import { renderApi } from '../web/views/api-integration.js';
import { renderUpdates } from '../web/views/updates.js';
import { renderLogs } from '../web/views/logs.js';

globalThis.location ??= { origin:'http://127.0.0.1:43123' };

const model = { id:'/Models/Qwen', name:'Qwen', repo:'org/qwen', installed:true, supported:true, startable:true };
const baseSnapshot = {
  update:{ active:{ version:'v1' } },
  settings:{ selected_model:model.id, max_tokens:256 },
  engine:{ state:'stopped', control_owner:null },
  models:[model],
  capabilities:{
    chat:{ supported:true }, streaming:{ supported:true }, benchmark:{ supported:true },
    quantize:{ supported:true, ready:true }, upload:{ supported:true, ready:true },
  },
  jobs:[], stats:{ total:{} }, resources:{}, system:{},
};

test('overview renders fresh service switch, attached detach, and explicit owned force controls', () => {
  const services = {
    confirmation_required:true,
    services:[{
      pid:42, kind:'tensorfold', executable:'/safe/tensorfold', start_time:'2026-09-29T10:00:00Z',
      model_path:'/Models/Old', port:8089, health:{ status:'ready' }, model_ids:['old'],
      control:{ supported:true, action:'stop_and_switch', reason:null }, snapshot_id:'fresh-snapshot', expires_in_seconds:30,
    }],
  };
  const stopped = renderOverview({ snapshot:baseSnapshot, pageData:{ services } });
  assert.match(stopped, /停止后切换/);
  assert.match(stopped, /30 秒/);
  assert.match(stopped, /data-form="service-switch"/);
  assert.match(stopped, /fresh-snapshot/);

  const attached = renderOverview({ snapshot:{ ...baseSnapshot, engine:{ state:'attached', control_owner:'external', model:'org/qwen' } }, pageData:{ services } });
  assert.match(attached, /断开连接/);
  assert.doesNotMatch(attached, /data-action="engine-stop"/);

  const timedOut = renderOverview({ snapshot:{ ...baseSnapshot, engine:{ state:'failed', control_owner:'manager', child_exit_confirmed:false, error:'Graceful stop timed out; explicit force is required' } }, pageData:{ services } });
  assert.match(timedOut, /强制停止自有服务/);
  assert.match(timedOut, /data-action="engine-force-stop"/);
  assert.doesNotMatch(timedOut, /data-action="engine-stop"/);
});

test('owned engine controls allow cancellation until child exit is confirmed', () => {
  const renderEngine = (engine) => renderOverview({
    snapshot:{ ...baseSnapshot, engine },
    pageData:{ services:{ services:[] } },
  });

  for (const engine of [
    { state:'starting', control_owner:'manager', pid:79282, child_exit_confirmed:false },
    { state:'ready', control_owner:'manager', pid:79282, child_exit_confirmed:false, started_at:1790645743.93256 },
    { state:'failed', control_owner:'manager', pid:79282, child_exit_confirmed:false, error:'Health check failed' },
  ]) {
    const output = renderEngine(engine);
    const stopButton = output.match(/<button[^>]*data-action="engine-stop"[^>]*>/)?.[0];
    assert.ok(stopButton, `${engine.state} must keep a stop control while the owned child may be alive`);
    assert.doesNotMatch(stopButton, /\sdisabled(?:\s|>)/, `${engine.state} stop must remain actionable`);
    assert.doesNotMatch(output, /data-action="engine-start"/);
    assert.doesNotMatch(output, /1790645743\.93256/);
  }

  const stopping = renderEngine({ state:'stopping', control_owner:'manager', pid:79282, child_exit_confirmed:false });
  const stoppingButton = stopping.match(/<button[^>]*data-action="engine-stop"[^>]*>/)?.[0];
  assert.ok(stoppingButton);
  assert.match(stoppingButton, /\sdisabled(?:\s|>)/);

  const exited = renderEngine({ state:'failed', control_owner:'manager', pid:null, child_exit_confirmed:true, error:'Process exited' });
  assert.match(exited, /data-action="engine-start"/);
  assert.match(exited, /data-action="engine-restart"/);
  assert.doesNotMatch(exited, /data-action="engine-stop"/);
});

test('owned service remains observable but is excluded from external switch controls', () => {
  const ownService = {
    pid:79282, kind:'owned-tensorfold-observation', executable:'/safe/owned', start_time:'2026-09-29T10:00:00Z',
    model_path:'/Models/OwnedObservation', port:8089, health:{ status:'starting' }, model_ids:['owned'],
    control:{ supported:false, action:null, reason:'Manager owns this service' }, snapshot_id:'owned-snapshot', expires_in_seconds:30,
  };
  const externalService = {
    pid:81, kind:'external-tensorfold', executable:'/safe/external', start_time:'2026-09-29T09:00:00Z',
    model_path:'/Models/External', port:8090, health:{ status:'ready' }, model_ids:['external'],
    control:{ supported:true, action:'stop_and_switch', reason:null }, snapshot_id:'external-snapshot', expires_in_seconds:30,
  };
  const output = renderOverview({
    snapshot:{
      ...baseSnapshot,
      engine:{ state:'starting', control_owner:'manager', pid:79282, child_exit_confirmed:false },
      resources:{ memory:{}, services:[ownService, externalService] },
    },
    pageData:{ services:{ services:[ownService, externalService] } },
  });

  assert.match(output, /owned-tensorfold-observation/);
  assert.match(output, /\/Models\/OwnedObservation/);
  assert.doesNotMatch(output, /owned-snapshot/);
  assert.match(output, /external-snapshot/);
});

test('overview and server use the actual native system and engine health schema', () => {
  const overview = renderOverview({
    snapshot:{ ...baseSnapshot, engine:{ state:'ready', control_owner:'manager', child_exit_confirmed:false, health_detail:{ memory:{ footprint:15438900816 } } } },
    pageData:{ services:{ services:[] } },
  });
  assert.match(overview, /引擎内存/);
  assert.match(overview, /14\.4 GB/);
  assert.match(overview, /上游 health 实际采样/);
  assert.doesNotMatch(overview, /运行内存/);

  const server = renderServer({
    snapshot:{ ...baseSnapshot, system:{ architecture:'arm64', hostname:'Mac', manager_pid:123 }, engine:{ state:'attached', pid:86999 } },
  });
  assert.match(server, /arm64/);
  assert.match(server, /App 自有生命周期/);
  assert.match(server, /外部兼容只读接入/);
  assert.match(server, /已验证确认切换/);
  assert.doesNotMatch(server, /按端口终止外部服务/);
});

test('attached verified services remain usable for chat and benchmark', () => {
  const snapshot = { ...baseSnapshot, engine:{ state:'attached', control_owner:'external', model:'org/qwen' } };
  const chat = renderChat({ snapshot, chat:{ options:{}, messages:[], streaming:false } });
  const benchmark = renderBenchmark({ snapshot, pageData:{ benchmark:{ results:[] } } });
  assert.doesNotMatch(chat, /disabled[^>]*>发送/);
  assert.doesNotMatch(benchmark, /disabled[^>]*>开始测试/);
  const models = renderModels({ snapshot:{ ...snapshot, models:[model, { ...model, id:'/Models/Other', name:'Other', repo:'org/other' }] } });
  assert.match(models, /已接入/);
  assert.doesNotMatch(models, /data-action="engine-start" data-value="\/Models\/Other"/);
});

test('download page limits choices to backend catalog sources and labels immutable identity honestly', () => {
  const output = downloadsView.renderDownloads({
    snapshot:{ ...baseSnapshot, jobs:[] },
    pageData:{
      catalog:{ default_directory:'/Managed/models', models:[{ repo:'org/qwen', name:'Qwen', supported:true, source:'huggingface', download_sources:['huggingface','hf-mirror'] }] },
      jobs:{ jobs:[{ id:'d1', kind:'download', status:'completed', params:{ source:'modelscope', revision:'master' }, result:{ revision:'abc', revision_kind:'file_manifest_sha256' } }] },
    },
  });
  assert.match(output, /name="catalog_model"/);
  assert.match(output, /huggingface:org\/qwen/);
  assert.match(output, /hf-mirror:org\/qwen/);
  assert.doesNotMatch(output, /name="repo"|name="revision"|name="directory"/);
  assert.match(output, /文件树快照/);
  assert.equal(typeof downloadsView.revisionKindLabel, 'function');
  assert.equal(downloadsView.revisionKindLabel('repository_commit'), '仓库提交');
  assert.equal(downloadsView.revisionKindLabel('file_manifest_sha256'), '文件树快照');
});

test('model advanced options serialize with strict types while framework page stays service-only', () => {
  assert.deepEqual(serializeSettings({
    drafter:'none', drafter_bits:'4', mtp_drafts:'3', no_drafts:'true', checkpoint_slots:'8',
    spill_gib:'2.5', max_snapshots:'5', reasoning_effort:'xhigh', thinking_budget:'128', name:'qwen-local',
    mtp_confidence:'',
  }), {
    drafter:'none', drafter_bits:4, mtp_drafts:3, no_drafts:true, checkpoint_slots:8,
    spill_gib:2.5, max_snapshots:5, reasoning_effort:'xhigh', thinking_budget:128, name:'qwen-local',
    mtp_confidence:null,
  });
  const output = renderEngineConfig({ snapshot:{ ...baseSnapshot, settings:{ ...baseSnapshot.settings, drafter:'none' } } });
  const dialog = renderModelConfigDialog({ snapshot:{ ...baseSnapshot, settings:{ ...baseSnapshot.settings, drafter:'none' } }, pageData:{ profiles:{ profiles:[] } }, routeQuery:new URLSearchParams() }, model.id);
  for (const name of ['drafter','drafter_bits','mtp_drafts','no_drafts','checkpoint_slots','spill_gib','max_snapshots','reasoning_effort','thinking_budget','name','mtp_confidence']) {
    if (['checkpoint_slots','spill_gib','max_snapshots'].includes(name)) assert.match(output, new RegExp(`name="${name}"`));
    else assert.match(dialog, new RegExp(`name="${name}"`));
  }
  assert.match(dialog, /CUDA-only/);
  assert.match(dialog, /启动前由已安装引擎 CLI 验证/);
  for (const name of ['context','max_tokens','temperature','top_p','top_k','thinking','drafter','mtp_drafts']) assert.doesNotMatch(output, new RegExp(`name="${name}"`));
});

test('stats and cache display backend aggregates, byte memory values, sources, parameters and attached read-only limits', () => {
  const request = {
    at:1, model:'org/qwen', status:499, elapsed:2, ttft:0.2, prefill_tps:10, decode_tps:20,
    cache_tokens:32, ttft_source:'observed_stream', prefill_tps_source:'reported_prefill_seconds',
    parameters:{ temperature:0 }, engine_parameters:{ context:32768 }, error:'Client cancelled',
  };
  const stats = renderStats({ snapshot:baseSnapshot, filters:{ statsModel:'', statsRange:'all' }, pageData:{ stats:{ total:{ requests:3, errors:1, cancelled:1, cache_tokens:32 }, requests:[request], models:[] } } });
  assert.match(stats, /缓存 tokens/);
  assert.match(stats, /32/);
  assert.match(stats, /observed_stream/);
  assert.match(stats, /Client cancelled/);
  assert.match(stats, /32768/);

  const cache = renderCache({
    snapshot:{ ...baseSnapshot, engine:{ state:'attached', health:true, health_detail:{ memory:{ active:14801518380, cache:51235264, peak:15522895064, budget:195827014042, footprint:15438900816 }, last_health_at:1790645743.93256 } }, stats:{ total:{ cache_tokens:32 }, models:[{ model:'org/qwen', cache_tokens:32 }] } },
    pageData:{ cache:{ can_clear:false, owned:true } },
  });
  for (const formatted of ['13.8 GB', '48.9 MB', '14.5 GB', '182.4 GB', '14.4 GB']) assert.match(cache, new RegExp(formatted));
  assert.doesNotMatch(cache, /14801518380|51235264|15522895064|195827014042|15438900816/);
  assert.doesNotMatch(cache, /1790645743\.93256/);
  assert.match(cache, /2026/);
  assert.match(cache, /32/);
  assert.match(cache, /外部服务仅提供只读用量/);
  assert.doesNotMatch(cache, /cached_tokens/);

  const emptyAndZero = renderCache({
    snapshot:{ ...baseSnapshot, engine:{ state:'stopped', health_detail:{ memory:{ active:0, cache:null } } } },
    pageData:{ cache:{} },
  });
  assert.match(emptyAndZero, /Active[\s\S]*?0 B/);
  assert.match(emptyAndZero, /Cache[\s\S]*?未采集/);
});

test('benchmark queue exposes actual status, parameters, partial results and cancellation', () => {
  const snapshot = {
    ...baseSnapshot,
    engine:{ state:'attached', control_owner:'external' },
    jobs:[
      { id:'a-running', kind:'accuracy', status:'running', params:{ suite:'all' }, progress:{ completed:1, total:3 } },
      { id:'a-paused', kind:'accuracy', status:'paused', params:{ suite:'all' }, progress:{ completed:1, total:3 } },
      { id:'b-running', kind:'benchmark', status:'running', params:{ runs:3 }, progress:{ run:2, total:3 } },
    ],
  };
  const benchmark = renderBenchmark({ snapshot, pageData:{ benchmark:{ results:[{
    id:'b1', status:'cancelled', error:'Client cancelled', model:'org/qwen', prompt:'hello',
    parameters:{ max_tokens:8, temperature:0 }, engine_parameters:{ context:32768 },
    results:[{ status:200, output_tokens:3 }],
  }] } } });
  assert.match(benchmark, /cancelled/);
  assert.match(benchmark, /已完成/);
  assert.match(benchmark, /32768/);
  assert.match(benchmark, /b-running:cancel/);
});

test('pure request builders preserve exact backend paths and bodies for click contracts', async () => {
  const contracts = await import('../web/contracts.js').catch(() => ({}));
  assert.equal(typeof contracts.serviceSwitchRequest, 'function');
  assert.deepEqual(contracts.serviceSwitchRequest('snap','/Models/Qwen'), { path:'/api/services/switch', options:{ method:'POST', body:{ snapshot_id:'snap', model:'/Models/Qwen', confirm:true } } });
  assert.deepEqual(contracts.engineStopRequest(true), { path:'/api/engine/stop', options:{ method:'POST', body:{ force:true } } });
  assert.deepEqual(contracts.engineDetachRequest(), { path:'/api/engine/detach', options:{ method:'POST', body:{} } });
  assert.deepEqual(contracts.credentialRequest('hf-upload','secret'), { path:'/api/credentials/hf-upload', options:{ method:'PUT', body:{ token:'secret' } } });
  assert.deepEqual(contracts.quantizeRequest({ model:'/Models/Qwen', name:'q4', bits:'4', group_size:'64', mode:'affine' }), { path:'/api/tools/quantize', options:{ method:'POST', body:{ model:'/Models/Qwen', name:'q4', bits:4, group_size:64, mode:'affine' } } });
  assert.deepEqual(contracts.uploadPrepareRequest({ model:'/Models/Qwen', repo:'owner/model', visibility:'public' }), { path:'/api/tools/uploads/prepare', options:{ method:'POST', body:{ model:'/Models/Qwen', repo:'owner/model', visibility:'public' } } });
  assert.deepEqual(contracts.uploadConfirmRequest('plan'), { path:'/api/tools/uploads/confirm', options:{ method:'POST', body:{ plan_id:'plan', confirm:true } } });
  assert.deepEqual(contracts.downloadRequest({ repo:'owner/model', source:'modelscope', revision:'', directory:'/Managed', use_credentials:'on' }), { path:'/api/downloads', options:{ method:'POST', body:{ repo:'owner/model', source:'modelscope', revision:'master', directory:'/Managed', use_credentials:true } } });
  assert.throws(() => contracts.downloadRequest({ repo:'owner/model', source:'hf-mirror', revision:'main', directory:'/Managed', use_credentials:'on' }), /第三方镜像/);
  let calls = 0;
  const unavailable = await contracts.optionalCredentialStatus(async () => {
    calls += 1;
    throw Object.assign(new Error('The app credential helper is unavailable'), { code:'credential_helper_unavailable' });
  });
  assert.equal(unavailable.unavailable_reason, 'The app credential helper is unavailable');
  assert.deepEqual(unavailable.providers, {});
  assert.equal(await contracts.optionalCredentialStatus(async () => { calls += 1; }, unavailable), unavailable);
  assert.equal(calls, 1);
  await assert.rejects(contracts.optionalCredentialStatus(async () => { throw Object.assign(new Error('offline'), { code:'http_error' }); }), /offline/);
});

test('poll policy refreshes live routes without replacing focused editors or streaming chat', async () => {
  const contracts = await import('../web/contracts.js');
  const livePages = ['overview', 'models', 'downloads', 'updates', 'stats', 'cache', 'logs', 'benchmark', 'server', 'api'];
  for (const page of livePages) {
    assert.equal(contracts.shouldPollLivePage(page, { editing:false, streaming:false }), true, `${page} should refresh while idle`);
  }
  for (const page of ['chat', 'engine-config', 'model-config', 'model-tools', 'accuracy', 'auth', 'capabilities']) {
    assert.equal(contracts.shouldPollLivePage(page, { editing:false, streaming:false }), false, `${page} should not be replaced by polling`);
  }
  assert.equal(contracts.shouldPollLivePage('benchmark', { editing:true, streaming:false }), false);
  assert.equal(contracts.shouldPollLivePage('chat', { editing:false, streaming:true }), false);

  const outsideForm = (tagName, extra = {}) => ({ tagName, closest:() => null, ...extra });
  for (const tag of ['INPUT', 'SELECT', 'TEXTAREA']) assert.equal(contracts.isPollEditingTarget(outsideForm(tag)), true);
  assert.equal(contracts.isPollEditingTarget(outsideForm('DIV', { isContentEditable:true })), true);
  assert.equal(contracts.isPollEditingTarget({ tagName:'BUTTON', closest:() => ({}) }), true, 'a focused control inside a form remains protected');
  assert.equal(contracts.isPollEditingTarget(outsideForm('BUTTON')), false);
  assert.equal(contracts.isPollEditingTarget(null), false);

  const appSource = readFileSync(new URL('../web/app.js', import.meta.url), 'utf8');
  const pollSource = appSource.slice(appSource.indexOf('setInterval(async () =>'));
  assert.match(pollSource, /await refreshSnapshot\(\{ render:false \}\)/, 'chrome snapshot still refreshes while editing');
  assert.match(pollSource, /await loadPageData\(polledPage, \{ render:false \}\)[\s\S]*renderCurrent\(\)/, 'live route data loads before rendering');
});

test('dirty edits remain protected after blur on every editable live page', async () => {
  const { shouldPollLivePage } = await import('../web/contracts.js');
  for (const page of ['server','overview','downloads','api']) {
    assert.equal(shouldPollLivePage(page, { editing:false, dirty:true }), false);
    assert.equal(shouldPollLivePage(page, { editing:false, dirty:false }), true);
  }
  const source = readFileSync(new URL('../web/app.js',import.meta.url),'utf8');
  assert.match(source,/pageElement.addEventListener\(type/);
  assert.match(source,/dirty:pageDirty/g);
  assert.match(source,/const result = await operation\(\);\s*pageDirty = false/);
});

test('every shipped page renders and every visible action or form has an application handler', async () => {
  const { renderResources } = await import('../web/views/resources.js');
  const { renderCache: cache } = await import('../web/views/cache.js');
  const state = {
    snapshot:{ ...baseSnapshot, app_version:'test', instance_id:'instance', engine:{ state:'stopped', control_owner:null }, update:{ active:{ version:'v1' } }, keys:[], profiles:[] },
    pageData:{ catalog:{ models:[], sources:[], default_directory:'/Managed' }, jobs:{ jobs:[] }, tools:{ active:null, pins:{} }, credentials:{ providers:{} }, profiles:{ profiles:[] }, keys:{ keys:[] }, updates:{}, logs:{ logs:[] }, benchmark:{ results:[] }, accuracy:{ cases:[], results:[] }, cache:{} },
    routeQuery:new URLSearchParams(), filters:{ statsModel:'', statsRange:'24h', logLevel:'', logQuery:'', logLimit:'50' }, chat:{ options:{}, messages:[], streaming:false },
  };
  const pages = {
    overview:renderOverview, stats:renderStats, cache, models:renderModels, downloads:downloadsView.renderDownloads,
    'engine-config':renderEngineConfig, server:renderServer, api:renderApi, updates:renderUpdates,
    logs:renderLogs, benchmark:renderBenchmark, chat:renderChat,
  };
  const appSource = readFileSync(new URL('../web/app.js', import.meta.url), 'utf8');
  const indexSource = readFileSync(new URL('../web/index.html', import.meta.url), 'utf8');
  const outputs = [];
  for (const [page, renderer] of Object.entries(pages)) {
    const output = renderer({ ...state, page });
    assert.equal(typeof output, 'string', `${page} must return markup`);
    assert.match(output, /tf-heading|tf-card/, `${page} must render visible content`);
    assert.match(indexSource, new RegExp(`data-page="${page}"`), `${page} must stay reachable from the menu`);
    outputs.push(output);
  }
  outputs.push(renderResources({}));
  const markup = outputs.join('\n');
  const actions = new Set([...markup.matchAll(/data-action="([^"]+)"/g)].map(match => match[1]).filter(Boolean));
  const forms = new Set([...markup.matchAll(/data-form="([^"]+)"/g)].map(match => match[1]));
  for (const action of actions) assert.match(appSource, new RegExp(`action === ['"]${action}['"]`), `click action ${action} must be handled`);
  for (const form of forms) assert.match(appSource, new RegExp(`action === ['"]${form}['"]`), `form ${form} must be handled`);
  assert.doesNotMatch(indexSource, /class="tf-nav"[^>]*disabled/, 'navigation must not strand a page behind a permanent disabled state');
  for (const removed of ['model-config','model-tools','auth','accuracy','capabilities']) assert.doesNotMatch(indexSource, new RegExp(`data-page="${removed}"`));
});

test('document head leaves frame embedding policy to the HTTP header and avoids a favicon 404', () => {
  const indexSource = readFileSync(new URL('../web/index.html', import.meta.url), 'utf8');
  const metaCsp = indexSource.match(/<meta http-equiv="Content-Security-Policy" content="([^"]+)">/)?.[1] ?? '';
  assert.doesNotMatch(metaCsp, /frame-ancestors/);
  assert.match(indexSource, /<link rel="icon" href="data:image\/svg\+xml,/);
});
