import test from 'node:test';
import assert from 'node:assert/strict';

import { renderOverview } from '../web/views/overview.js';
import { renderChat } from '../web/views/chat.js';
import { renderBenchmark } from '../web/views/benchmark.js';
import * as downloadsView from '../web/views/downloads.js';
import { renderModelTools } from '../web/views/model-tools.js';
import { renderEngineConfig } from '../web/views/engine-config.js';
import { renderStats } from '../web/views/stats.js';
import { renderCache } from '../web/views/cache.js';
import { renderAccuracy } from '../web/views/accuracy.js';
import { serializeSettings } from '../web/views/settings.js';
import { readFileSync } from 'node:fs';
import { renderModels } from '../web/views/models.js';
import { renderModelConfig } from '../web/views/model-config.js';
import { renderServer } from '../web/views/server.js';
import { renderApi } from '../web/views/api-integration.js';
import { renderAuth } from '../web/views/auth.js';
import { renderUpdates } from '../web/views/updates.js';
import { renderLogs } from '../web/views/logs.js';
import { renderCapabilities } from '../web/views/capabilities.js';

globalThis.location ??= { origin:'http://127.0.0.1:43123' };

const model = { id:'/Models/Qwen', name:'Qwen', repo:'org/qwen', installed:true, supported:true };
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

  const timedOut = renderOverview({ snapshot:{ ...baseSnapshot, engine:{ state:'failed', control_owner:'manager', error:'Graceful stop timed out; explicit force is required' } }, pageData:{ services } });
  assert.match(timedOut, /强制停止自有服务/);
  assert.match(timedOut, /data-action="engine-force-stop"/);
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

test('tools page uses runtime status, password-only credentials, affine quantization, and upload preview', () => {
  const output = renderModelTools({
    snapshot:{ ...baseSnapshot, jobs:[{ id:'install-1', kind:'tool_install', status:'running', params:{}, progress:{ phase:'install_pinned_packages' } }] },
    pageData:{
      tools:{ active:null, pins:{ 'mlx-lm':'backend-version', 'huggingface-hub':'backend-hub' } },
      credentials:{ providers:{
        'hf-download':{ provider:'hf-download', configured:true },
        'hf-upload':{ provider:'hf-upload', configured:false },
        'modelscope-download':{ provider:'modelscope-download', configured:false },
      } },
      uploadPlan:{ plan_id:'plan-1', repo:'owner/model', visibility:'public', existing:false, size_bytes:4096, files:[{ path:'config.json', size_bytes:4096, sha256:'a'.repeat(64) }] },
    },
  });
  assert.match(output, /backend-version/);
  assert.match(output, /install_pinned_packages/);
  assert.match(output, /type="password"/);
  assert.match(output, /已配置/);
  assert.doesNotMatch(output, /private-example-token/);
  assert.match(output, /name="group_size"/);
  assert.match(output, /value="affine"/);
  assert.match(output, /实际可见性/);
  assert.match(output, /新建公开仓库/);
  assert.match(output, /data-action="upload-confirm"/);
});

test('capability table treats installed-but-not-ready tools as unavailable', () => {
  const output = renderCapabilities({ snapshot:{ capabilities:{ quantize:{ supported:true, ready:false, reason:'Install tools first' } } } });
  assert.match(output, /不可用/);
  assert.match(output, /Install tools first/);
});

test('download page supports scoped official credentials and labels immutable identity honestly', () => {
  const output = downloadsView.renderDownloads({
    snapshot:{ ...baseSnapshot, jobs:[] },
    pageData:{
      catalog:{ sources:[
        { id:'huggingface', credentials_supported:true },
        { id:'hf-mirror', third_party:true, credentials_supported:false },
        { id:'modelscope', credentials_supported:true },
      ], default_directory:'/Managed/models', models:[] },
      credentials:{ providers:{ 'hf-download':{ configured:true }, 'modelscope-download':{ configured:false } } },
      jobs:{ jobs:[{ id:'d1', kind:'download', status:'completed', params:{ source:'modelscope', revision:'master' }, result:{ revision:'abc', revision_kind:'file_manifest_sha256' } }] },
    },
  });
  assert.match(output, /name="use_credentials"/);
  assert.match(output, /官方来源/);
  assert.match(output, /默认 master/);
  assert.match(output, /文件树快照/);
  assert.equal(typeof downloadsView.revisionKindLabel, 'function');
  assert.equal(downloadsView.revisionKindLabel('repository_commit'), '仓库提交');
  assert.equal(downloadsView.revisionKindLabel('file_manifest_sha256'), '文件树快照');
});

test('advanced options serialize with strict types and show runtime support reasons', () => {
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
  for (const name of ['drafter','drafter_bits','mtp_drafts','no_drafts','checkpoint_slots','spill_gib','max_snapshots','reasoning_effort','thinking_budget','name','mtp_confidence']) {
    assert.match(output, new RegExp(`name="${name}"`));
  }
  assert.match(output, /CUDA-only/);
  assert.match(output, /启动前由已安装引擎 CLI 验证/);
});

test('stats and cache display backend aggregates, cache_tokens, sources, parameters and attached read-only limits', () => {
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
    snapshot:{ ...baseSnapshot, engine:{ state:'attached', health:true, health_detail:{ memory:{ active_bytes:1024 }, last_health_at:123 } }, stats:{ total:{ cache_tokens:32 }, models:[{ model:'org/qwen', cache_tokens:32 }] } },
    pageData:{ cache:{ can_clear:false, owned:true } },
  });
  assert.match(cache, /1.0 KB/);
  assert.match(cache, /32/);
  assert.match(cache, /外部服务仅提供只读用量/);
  assert.doesNotMatch(cache, /cached_tokens/);
});

test('benchmark and accuracy queues expose actual status, parameters, partial results, pause resume and cancel', () => {
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
  assert.match(benchmark, /部分结果/);
  assert.match(benchmark, /32768/);
  assert.match(benchmark, /b-running:cancel/);

  const accuracy = renderAccuracy({ snapshot, pageData:{ accuracy:{ cases:[{ id:'c', name:'n', prompt:'p', expected:'e', match:'exact', max_tokens:8 }], results:[] } } });
  assert.match(accuracy, /a-running:pause/);
  assert.match(accuracy, /a-running:cancel/);
  assert.match(accuracy, /a-paused:resume/);
  assert.match(accuracy, /suite/);
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
    'model-config':renderModelConfig, 'model-tools':renderModelTools, 'engine-config':renderEngineConfig,
    server:renderServer, api:renderApi, auth:renderAuth, updates:renderUpdates, logs:renderLogs,
    benchmark:renderBenchmark, accuracy:renderAccuracy, chat:renderChat, capabilities:renderCapabilities,
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
});

test('document head leaves frame embedding policy to the HTTP header and avoids a favicon 404', () => {
  const indexSource = readFileSync(new URL('../web/index.html', import.meta.url), 'utf8');
  const metaCsp = indexSource.match(/<meta http-equiv="Content-Security-Policy" content="([^"]+)">/)?.[1] ?? '';
  assert.doesNotMatch(metaCsp, /frame-ancestors/);
  assert.match(indexSource, /<link rel="icon" href="data:image\/svg\+xml,/);
});
