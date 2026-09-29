import test from 'node:test';
import assert from 'node:assert/strict';

import { escapeHtml, displayValue } from '../web/views/shared.js';
import { ApiError, parseApiError, createApiClient, resolveBootstrapToken } from '../web/api.js';
import { serializeSettings, partitionProfileConfig } from '../web/views/settings.js';
import { exportTextFile } from '../web/export.js';
import { chooseLaunchModel, getLaunchGate } from '../web/views/overview.js';
import { canValidateModel } from '../web/views/models.js';
import { renderCache } from '../web/views/cache.js';

test('stopped engine with null health still renders cache controls', () => {
  assert.match(renderCache({snapshot:{engine:{state:'stopped',health:null}},pageData:{cache:{can_clear:true}}}), /清理受管快照/);
});

test('escapeHtml escapes markup and attribute delimiters from backend text', () => {
  assert.equal(
    escapeHtml(`<img src=x onerror="alert('x')"> & done`),
    '&lt;img src=x onerror=&quot;alert(&#39;x&#39;)&quot;&gt; &amp; done',
  );
});

test('displayValue renders only nullish metrics as uncollected', () => {
  assert.equal(displayValue(null), '未采集');
  assert.equal(displayValue(undefined), '未采集');
  assert.equal(displayValue(0), '0');
  assert.equal(displayValue(false), '否');
});

test('parseApiError uses the protocol error and falls back safely', async () => {
  const structured = new Response(
    JSON.stringify({ error: { message: '端口被占用', code: 'port_conflict' } }),
    { status: 409, headers: { 'content-type': 'application/json' } },
  );
  const first = await parseApiError(structured);
  assert.equal(first.message, '端口被占用');
  assert.equal(first.code, 'port_conflict');
  assert.equal(first.status, 409);

  const malformed = new Response('<html>bad gateway</html>', { status: 502 });
  const second = await parseApiError(malformed);
  assert.equal(second.message, '请求失败（HTTP 502）');
  assert.equal(second.code, 'http_error');
});

test('authenticated client sends same-origin bearer requests and rejects API failures', async () => {
  const calls = [];
  const client = createApiClient({
    getToken: async () => 'runtime-secret',
    fetchImpl: async (url, options) => {
      calls.push({ url, options });
      return new Response(JSON.stringify({ error: { message: '未就绪', code: 'not_ready' } }), {
        status: 409,
        headers: { 'content-type': 'application/json' },
      });
    },
  });

  await assert.rejects(
    client.request('/api/engine/start', { method: 'POST', body: { model: 'safe/model' } }),
    (error) => error instanceof ApiError && error.code === 'not_ready',
  );
  assert.equal(calls[0].url, '/api/engine/start');
  assert.equal(calls[0].options.headers.Authorization, 'Bearer runtime-secret');
  assert.equal(calls[0].options.headers['Content-Type'], 'application/json');
  assert.equal(calls[0].options.credentials, 'same-origin');
  assert.equal(calls[0].options.body, '{"model":"safe/model"}');
});

test('client refuses non-management and cross-origin request targets', async () => {
  const client = createApiClient({ getToken: async () => 'token', fetchImpl: async () => new Response('{}') });
  await assert.rejects(client.request('https://attacker.example/api/state'), /same-origin management path/);
  await assert.rejects(client.request('/v1/models'), /same-origin management path/);
});

test('serializeSettings emits protocol types and drops unknown or secret fields', () => {
  const settings = serializeSettings({
    selected_model: 'org/model',
    engine_python: '/tmp/python',
    model_dirs: ' /Models/one\n\n/Models/two ',
    engine_port: '18080',
    gateway_port: '8080',
    context: '32768',
    max_tokens: '4096',
    temperature: '0.7',
    top_p: '0.8',
    top_k: '20',
    parallel: '4',
    thinking: 'true',
    prompt_cache_gib: '8',
    mlx_cache_gib: '3.5',
    snapshot_dir: '/Managed/cache',
    api_key: 'must-not-leave-the-form',
    surprise: 'drop-me',
  });

  assert.deepEqual(settings, {
    selected_model: 'org/model',
    engine_python: '/tmp/python',
    model_dirs: ['/Models/one', '/Models/two'],
    engine_port: 18080,
    gateway_port: 8080,
    context: 32768,
    max_tokens: 4096,
    temperature: 0.7,
    top_p: 0.8,
    top_k: 20,
    parallel: 4,
    thinking: true,
    prompt_cache_gib: 8,
    mlx_cache_gib: 3.5,
    snapshot_dir: '/Managed/cache',
  });
});

test('serializeSettings rejects invalid numeric input before an API write', () => {
  assert.throws(() => serializeSettings({ engine_port: 'not-a-port' }), /engine_port/);
  assert.throws(() => serializeSettings({ temperature: '' }), /temperature/);
});

test('serializeSettings preserves the backend parallel auto mode', () => {
  assert.deepEqual(serializeSettings({ parallel:'auto' }), { parallel:'auto' });
});

test('development fragment bootstrap requires explicit loopback dev mode and erases fragment', async () => {
  const replaced = [];
  const location = {
    hostname: '127.0.0.1',
    pathname: '/',
    search: '?dev=1',
    hash: '#token=dev-token',
  };
  const token = await resolveBootstrapToken({
    location,
    history: { replaceState: (...args) => replaced.push(args) },
    webkit: undefined,
  });
  assert.equal(token, 'dev-token');
  assert.deepEqual(replaced, [[null, '', '/?dev=1']]);

  await assert.rejects(
    resolveBootstrapToken({
      location: { ...location, hostname: 'manager.example' },
      history: { replaceState() {} },
      webkit: undefined,
    }),
    /Native bootstrap unavailable/,
  );
});

test('exportTextFile prefers the native save bridge and treats user cancel as a normal result', async () => {
  const messages = [];
  const result = await exportTextFile({
    name: 'stats.csv',
    content: 'a,b\n1,2\n',
    webkit: { messageHandlers: { exportFile: { postMessage: async (payload) => {
      messages.push(payload);
      return { saved:false };
    } } } },
  });
  assert.deepEqual(messages, [{ name:'stats.csv', content:'a,b\n1,2\n' }]);
  assert.deepEqual(result, { saved:false });
});

test('chooseLaunchModel ignores unsupported scanned models and prefers a verified installed checkpoint', () => {
  const snapshot = {
    settings: { selected_model:'/Models/DeepSeek-V4-AWQ' },
    engine: { model:null },
    models: [
      { id:'/Models/DeepSeek-V4-AWQ', name:'DeepSeek-V4-AWQ', installed:true, supported:false },
      { id:'/Models/Qwen3.8-27B', name:'Qwen3.8-27B', installed:true, supported:true },
      { id:'/Models/Qwen-Missing', name:'Qwen Missing', installed:false, supported:true },
    ],
  };
  const choice = chooseLaunchModel(snapshot);
  assert.equal(choice.selected, '/Models/Qwen3.8-27B');
  assert.deepEqual(choice.options.map((model) => model.id), ['/Models/Qwen3.8-27B']);
});

test('getLaunchGate blocks engine controls until a runtime is installed', () => {
  assert.deepEqual(
    getLaunchGate({ update:{ active:null }, engine:{ state:'stopped' } }, '/Models/Qwen3.8-27B'),
    { allowed:false, reason:'请先安装 TensorFold 引擎' },
  );
  assert.deepEqual(
    getLaunchGate({ update:{ active:{ version:'v0.3.6' } }, engine:{ state:'stopped' } }, ''),
    { allowed:false, reason:'请先安装并选择受支持模型' },
  );
});

test('streamChat preserves delivered text but rejects EOF before the SSE done marker', async () => {
  const chunks = [];
  const client = createApiClient({
    getToken: async () => 'token',
    fetchImpl: async () => new Response('data: {"choices":[{"delta":{"content":"partial"}}]}\n\n', {
      status:200,
      headers:{ 'content-type':'text/event-stream' },
    }),
  });
  await assert.rejects(
    client.streamChat({ messages:[] }, { onDelta:(text) => chunks.push(text) }),
    (error) => error instanceof ApiError && error.code === 'stream_interrupted',
  );
  assert.deepEqual(chunks, ['partial']);
});

test('canValidateModel only offers real CLI validation for complete unsupported local models', () => {
  assert.equal(canValidateModel({ installed:true, supported:false, id:'/Models/custom' }), true);
  assert.equal(canValidateModel({ installed:false, supported:false, id:'/Models/missing' }), false);
  assert.equal(canValidateModel({ installed:true, supported:true, id:'/Models/verified' }), false);
  assert.equal(canValidateModel({ installed:true, supported:false, id:'owner/remote' }), false);
});

test('partitionProfileConfig accepts only persisted profile fields and separates model settings', () => {
  assert.deepEqual(partitionProfileConfig({
    selected_model:'/Models/Qwen', temperature:0.5, top_p:0.9, thinking:false,
  }), {
    settings:{ selected_model:'/Models/Qwen', temperature:0.5, top_p:0.9, thinking:false },
    modelConfig:{ temperature:0.5, top_p:0.9, thinking:false },
  });
  assert.throws(() => partitionProfileConfig({ engine_port:18080 }), /engine_port/);
  assert.throws(() => partitionProfileConfig({ api_key:'secret' }), /api_key/);
});
