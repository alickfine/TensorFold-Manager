/* 一致性闸门专用 mock：在纯浏览器里冒充原生壳的 window.bridge。
   真壳（WKWebView 注入）与假壳（本文件）对 app.js 透明。 */
(() => {
  const FAMILY = [
    { name: 'Nemotron 3.5 Lightning 30B', id: 'TensorFold/NVIDIA-Nemotron-3.5-Lightning-30B-A3B-MLX-4bit', size_gb: 17, note: '内置 MTP 草稿头' },
    { name: 'Qwen3.8-27B (4bit)', id: 'TensorFold/Qwen3.8-27B-MLX-4bit', size_gb: 15, note: '可配 DFlash2 草稿模型' },
    { name: 'Qwen3.8 Flash Next', id: 'TensorFold/Qwen3.8-Flash-Next-MLX-4bit-MTP', size_gb: 15, note: '内置 MTP 头' },
    { name: 'GLM-5.3-Flash', id: 'TensorFold/GLM-5.3-Flash-MLX-4bit-MTP', size_gb: 20, note: '256GB Mac 可跑；可配 --vision' },
    { name: 'Qwen3.6-35B-A3B', id: 'TensorFold/Qwen3.6-35B-A3B-MLX-4bit-MTP', size_gb: 20, note: '内置 MTP 头' },
    { name: 'DeepSeek-V4-Flash DSpark', id: 'TensorFold/DeepSeek-V4-Flash-DSpark-MLX', size_gb: 40, note: '256GB Mac 可跑' },
  ];
  const METHODS = {
    families: () => FAMILY,
    models_installed: () => [{ id: 'TensorFold/Qwen3.8-27B-MLX-4bit', size_gb: 14.98 }],
    pull_status: () => ({}),
    overview: () => ({
      instances: [], proxy_port: 59999, mem_total: 256, mem_free: 190,
      metrics_latest: { tps: 0, kv: 0, running: 0, waiting: 0, footprint_gb: 0 },
      per: {}, series: {},
    }),
    settings: () => ({ installed: true, cli: '/usr/local/bin/tensorfold', version: '0.6.4', app_version: '2.0.0', proxy_port: 59999 }),
    app_settings_get: () => ({ default_context: 32768, parallel: 4, prompt_cache_gib: 16, default_model: '', autostart_engine: false, auto_update_check: true, menubar: true, close_to_menubar: true, theme: 'light' }),
    app_settings_save: (a) => a,
    model_settings_get: () => ({ context: 32768, max_tokens: 4096, temperature: null, top_p: null, thinking: false, reasoning_effort: null, parallel: null, port: null, mtp_drafts: null, mtp_confidence: null, kv_dtype: null, prompt_cache_gib: null, vision: false, backend: null }),
    model_settings_save: () => ({ ok: true }),
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
