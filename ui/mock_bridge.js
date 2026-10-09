/* 一致性闸门专用 mock：在纯浏览器里冒充原生壳的 window.bridge。
   真壳（WKWebView 注入）与假壳（本文件）对 app.js 透明。 */
(() => {
  // 闸门可翻转的开关：覆盖「草稿模型已下载 / 未下载」「推测解码开 / 关」两条分支
  const S = window.__mock = { draftCached: true, drafts: true };
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
    pull_status: () => ({}),
    overview: () => ({
      instances: [], proxy_port: 59999, mem_total: 256, mem_free: 190,
      metrics_latest: { tps: 0, kv: 0, running: 0, waiting: 0, footprint_gb: 0 },
      per: {}, series: {},
    }),
    settings: () => ({ installed: true, cli: '/usr/local/bin/tensorfold', version: '0.6.4', app_version: '2.0.0', proxy_port: 59999 }),
    app_settings_get: () => ({ default_context: 32768, parallel: 4, prompt_cache_gib: 16, default_model: '', autostart_engine: false, auto_update_check: true, menubar: true, close_to_menubar: true, theme: 'light' }),
    app_settings_save: (a) => a,
    model_settings_get: () => ({ context: 32768, max_tokens: 4096, temperature: null, top_p: null, thinking: false, reasoning_effort: null, parallel: null, port: null, mtp_drafts: null, mtp_confidence: null, kv_dtype: null, prompt_cache_gib: null, vision: false, backend: null, drafts: S.drafts, _raw: {} }),
    model_settings_save: (a) => { window.__lastSave = a; return { ok: true }; },
    model_settings_reset: () => ({ ok: true }),
    model_pull: () => ({ ok: true }),
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
    update_status: () => ({ checked_at: 0, engine: null, app: null, error: '' }),
    update_check: () => ({ checked_at: 1, engine: { available: true, latest: '0.6.5' }, app: { available: false }, error: '' }),
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
