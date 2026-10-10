/* 一致性闸门专用 mock：在纯浏览器里冒充原生壳的 window.bridge。
   真壳（WKWebView 注入）与假壳（本文件）对 app.js 透明。 */
(() => {
  // 闸门可翻转的开关：覆盖「草稿模型已下载 / 未下载」「推测解码开 / 关」「下载进度条」
  // 「监听范围 本机 / 局域网」几条分支
  const S = window.__mock = { draftCached: true, drafts: true, pulling: false, listen: 'local',
                              updStatus: null, applyFail: false };
  // 每核占用 mock（Apple Silicon：12 性能核 + 24 能效核，与真机读数同构）
  const ARM_P12 = [88, 74, 91, 66, 82, 79, 95, 70, 63, 87, 72, 80];
  const ARM_E24 = [41, 33, 52, 28, 45, 37, 22, 49, 31, 44, 26, 38,
                   55, 30, 43, 35, 48, 24, 39, 29, 46, 27, 36, 42];
  // 后端 api.families() 会给每张卡带上 accel（draft_status），mock 保持同构
  const DRAFT = {
    draft_repo: 'z-lab/Qwen3.8-27B-DFlash2',
    draft_cached: true, draft_size_gb: 3.58,
    draft_used_by: ['TensorFold/Qwen3.8-27B-MLX-4bit'],
  };
  const FAMILY = [
    { name: 'Nemotron 3.5 Lightning 30B', id: 'TensorFold/NVIDIA-Nemotron-3.5-Lightning-30B-A3B-MLX-4bit', size_gb: 17, note: '内置 MTP 草稿头', accel: {} },
    { name: 'Qwen3.8-27B (4bit)', id: 'TensorFold/Qwen3.8-27B-MLX-4bit', size_gb: 15, note: '可配 DFlash2 草稿模型', accel: DRAFT },
    { name: 'Qwen3.8 Flash Next', id: 'TensorFold/Qwen3.8-Flash-Next-MLX-4bit-MTP', size_gb: 15, note: '内置 MTP 头', accel: {} },
    { name: 'GLM-5.3-Flash', id: 'TensorFold/GLM-5.3-Flash-MLX-4bit-MTP', size_gb: 20, note: '256GB Mac 可跑；可配 --vision', accel: {} },
    { name: 'Qwen3.6-35B-A3B', id: 'TensorFold/Qwen3.6-35B-A3B-MLX-4bit-MTP', size_gb: 20, note: '内置 MTP 头', accel: {} },
    { name: 'DeepSeek-V4-Flash DSpark', id: 'TensorFold/DeepSeek-V4-Flash-DSpark-MLX', size_gb: 40, note: '256GB Mac 可跑', accel: {} },
  ];
  const SCAN = {
    roots: [
      { label: 'Hugging Face 缓存', path: '~/.cache/huggingface/hub', custom: false, exists: true, count: 1 },
      { label: 'oMLX', path: '~/.omlx/models', custom: false, exists: true, count: 4 },
      { label: 'MTPLX', path: '~/.mtplx/models', custom: false, exists: true, count: 1 },
      { label: 'LM Studio', path: '~/.lmstudio/models', custom: false, exists: false, count: 0 },
      { label: '自定义', path: '/Users/me/models', custom: true, exists: true, count: 2 },
    ],
    extra: ['/Users/me/models'],
    found: 8,
  };
  const NET = () => ({
    listen: S.listen,
    bind_host: S.listen === 'lan' ? '0.0.0.0' : '127.0.0.1',
    proxy_port: 59999,
    proxy_host: S.listen === 'lan' ? '0.0.0.0' : '127.0.0.1',
    lan_ip: '192.168.100.101',
    local_url: 'http://127.0.0.1:59999/v1',
    lan_url: 'http://192.168.100.101:59999/v1',
    running: [],
  });
  // 累计用量账本（与 backend/usage.py 的 summary() 同构）
  const USAGE = {
    totals: { requests: 42, prompt_tokens: 1850000, generation_tokens: 2640900, total_tokens: 4490900,
              drafted: 900, accepted: 620, gen_tps: 55.2, prefill_tps: 769.5 },
    models: [
      { model: 'TensorFold/Qwen3.8-27B-MLX-4bit', requests: 40, prompt_tokens: 1720000,
        generation_tokens: 2540000, total_tokens: 4260000, gen_tps: 55.3 },
      { model: 'TensorFold/GLM-5.3-Flash-MLX-4bit-MTP', requests: 2, prompt_tokens: 130000,
        generation_tokens: 100900, total_tokens: 230900, gen_tps: 51.8 },
    ],
    since: 1789000000,
    path: '~/.tensorfold-manager/usage.json',
  };
  // 闸门里可直接拿去 renderMetrics 的同一份账本
  window.__mockUsage = USAGE;
  const METHODS = {
    families: () => FAMILY.map(f => (f.accel && f.accel.draft_repo)
      ? { ...f, accel: { ...f.accel, draft_cached: S.draftCached, draft_size_gb: S.draftCached ? DRAFT.draft_size_gb : 0 } }
      : f),
    models_installed: () => [
      { id: 'TensorFold/Qwen3.8-27B-MLX-4bit', ref: 'TensorFold/Qwen3.8-27B-MLX-4bit', size_gb: 14.98, source: 'hf', root_label: 'Hugging Face 缓存', deletable: true, role: 'model', used_by: [] },
      { id: 'z-lab/Qwen3.8-27B-DFlash2', ref: 'z-lab/Qwen3.8-27B-DFlash2', size_gb: 3.58, source: 'hf', root_label: 'Hugging Face 缓存', deletable: true, role: 'draft', used_by: ['TensorFold/Qwen3.8-27B-MLX-4bit'] },
      { id: 'GLM-5.3-Flash-MLX-4bit-MTP', ref: '/Users/fanwenbin/.omlx/models/GLM-5.3-Flash-MLX-4bit-MTP', size_gb: 19.4, source: 'oMLX', root_label: 'oMLX', deletable: false, role: 'model', used_by: [] },
    ],
    scan_dirs: () => SCAN,
    scan_dir_add: () => ({ ok: true, added: true, ...SCAN }),
    scan_dir_remove: () => ({ ok: true, ...SCAN }),
    pick_dir: () => ({ ok: true, path: '/Users/me/models' }),
    pull_status: () => (S.pulling ? {
      'TensorFold/Qwen3.8-27B-MLX-4bit': {
        status: 'downloading', done_gb: 6.4, total_gb: 15, percent: 43, elapsed: 725,
      },
    } : {}),
    overview: () => ({
      instances: [], proxy_port: 59999, mem_total: 256, mem_free: 190,
      listen: S.listen, bind_host: S.listen === 'lan' ? '0.0.0.0' : '127.0.0.1',
      lan_ip: S.listen === 'lan' ? '192.168.100.101' : '',
      // 本机性能：核心构成与占用率都来自真实读数（sysctl / ioreg / psutil）
      cpu_cores: 36, cpu_physical: 36, cpu_p: 12, cpu_e: 24,
      cpu_model: 'Apple M5 Ultra', cpu_label: '12P + 24E · 36 逻辑核',
      gpu_name: 'Apple M5 Ultra', gpu_cores: 80, gpu_label: 'Apple M5 Ultra · 80 核',
      load: [11.24, 12.41, 10.93], disk_free_gb: 412.7,
      metrics_latest: {
        tps: 55, gen_avg_tps: 55.2, prefill_tps: 769, prefill_avg_tps: 769.5, ttft_avg_ms: 412,
        kv: 0, running: 0, waiting: 0, footprint_gb: 0,
        prompt_tokens: 0, gen_tokens_total: 0, requests_done: 0,
        cpu_percent: 62, gpu_percent: 71, mem_free: 190,
        // 36 核：前 12 个是性能核（忙），后 24 个能效核（轻）
        cpu_per: [...ARM_P12, ...ARM_E24],
      },
      per: {}, series: {
        cpu_percent: { kind: 'percent', values: [48, 55, 71, 62, 58, 66, 62] },
        gpu_percent: { kind: 'percent', values: [30, 44, 68, 80, 74, 69, 71] },
      }, usage: USAGE,
    }),
    network: () => NET(),
    set_listen: (a) => {
      S.listen = a.listen === 'lan' ? 'lan' : 'local';
      window.__listenCalls = (window.__listenCalls || []).concat([S.listen]);
      return { ok: true, ...NET() };
    },
    restart_instances: () => {
      window.__restarted = (window.__restarted || 0) + 1;
      return { ok: true, restarted: [], failed: [] };
    },
    usage_status: () => USAGE,
    usage_reset: () => {
      window.__usageReset = (window.__usageReset || 0) + 1;
      return { ok: true, ...USAGE };
    },
    settings: () => ({ installed: true, cli: '/usr/local/bin/tensorfold', version: '0.6.4', app_version: '2.0.0', proxy_port: 59999 }),
    app_settings_get: () => ({ default_context: 32768, parallel: 4, prompt_cache_gib: 16, default_model: '', listen: S.listen, autostart_engine: false, auto_update_check: true, menubar: true, close_to_menubar: true, theme: 'light' }),
    app_settings_save: (a) => a,
    model_settings_get: () => ({ context: 32768, max_tokens: 4096, temperature: null, top_p: null, thinking: false, reasoning_effort: null, parallel: null, port: null, mtp_drafts: null, mtp_confidence: null, kv_dtype: null, prompt_cache_gib: null, vision: false, backend: null, drafts: S.drafts, _raw: {} }),
    model_settings_save: (a) => { window.__lastSave = a; return { ok: true }; },
    model_settings_reset: () => ({ ok: true }),
    model_pull: () => ({ ok: true }),
    model_delete: () => { window.__modelDel = (window.__modelDel || 0) + 1; return { ok: true }; },
    model_info: (a) => {
      const ref = (a && a.ref) || 'TensorFold/Qwen3.8-27B-MLX-4bit';
      const hasDraft = /Qwen3\.8-27B-MLX-4bit$/.test(ref);
      return {
        ref, found: true, context_max: 262144, vocab_size: 248320, model_type: 'qwen3_5',
        architectures: ['Qwen3_5ForConditionalGeneration'],
        defaults: { context: 262144, max_tokens: null, temperature: 1.0, top_p: 0.95, top_k: 20 },
        capabilities: { vision: true, thinking: true, mtp: true },
        accel: {
          builtin_mtp: true, mtp_layers: 1,
          draft_repo: hasDraft ? DRAFT.draft_repo : '',
          draft_cached: hasDraft && S.draftCached,
          draft_size_gb: hasDraft && S.draftCached ? DRAFT.draft_size_gb : 0,
          draft_used_by: hasDraft ? DRAFT.draft_used_by : [],
        },
        display: ref.split('/').pop(), provider: ref.split('/')[0],
      };
    },
    update_status: () => S.updStatus || ({ checked_at: 0, engine: null, app: null, error: '' }),
    update_check: () => S.updStatus || ({ checked_at: 1, engine: { available: true, latest: '0.6.5', current: '0.6.4' }, app: { available: false, current: '2.0.0' }, error: '' }),
    // 一键升级：闸门要能断言"点确定后真的调到了后端"，并验证升级后状态行会收口。
    // 旧 mock 里**没有**这两个方法 → 桥直接 reject('unknown method')，
    // 于是升级链路从来没被闸门走过，按钮坏了也没人发现。
    update_apply_engine: () => {
      window.__applyCalls = (window.__applyCalls || 0) + 1;
      if (S.applyFail) return { ok: false, error: '下载失败: SHA256 不符' };
      if (S.updStatus && S.updStatus.engine) {
        S.updStatus = { ...S.updStatus, checked_at: Date.now() / 1000,
          engine: { ...S.updStatus.engine, available: false, current: S.updStatus.engine.latest } };
      }
      return { ok: true, version: '1.0.4', restarted: [], restart_failed: [],
               restarted_hint: '已用新引擎重新加载: Qwen3.8-27B-MLX-4bit' };
    },
    update_open_app: () => { window.__openAppCalls = (window.__openAppCalls || 0) + 1; return { ok: true }; },
    chat_list: () => [],
    chat_create: ({ chat }) => Object.assign({ id: 'mock1', messages: [] }, chat, { updated: Date.now() / 1000 }),
    chat_get: () => null,
    chat_save: () => ({ ok: true }),
    engine_stop: () => ({ ok: true }),
    engine_start: () => ({ ok: true }),
    copy_text: () => ({ ok: true }),
    open_hf_cache: () => ({ ok: true }),
  };
  window.bridge = {
    call: (method, args) => {
      const fn = METHODS[method];
      if (!fn) return Promise.reject('mock: unknown method ' + method);
      return Promise.resolve(fn(args || {}));
    },
    on: () => {},
    _push: () => {},
  };
})();
