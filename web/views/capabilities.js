import { h, html } from './shared.js';

const LABELS = {
  chat_completions:'Chat Completions', completions:'Text Completions', streaming:'SSE 流式输出', tool_calling:'Tool calling',
  quantize:'量化', upload:'上传', external_engine_python:'外部 Engine Python', vision:'图片输入', audio:'音频输入',
  embeddings:'Embeddings', multi_model:'多模型热加载', cache_clear:'受管缓存清理', benchmark:'基准测试', downloads:'模型下载', updates:'引擎更新',
};

function normalize(name, raw) {
  if (raw === true || raw === false) return { name, enabled:raw, reason:'' };
  if (raw && typeof raw === 'object') {
    const enabled = Boolean(raw.enabled ?? raw.available ?? raw.supported) && raw.ready !== false && raw.available !== false;
    return { name, enabled, reason:raw.reason ?? raw.message ?? (enabled ? '' : '能力尚未准备完成'), source:raw.source };
  }
  return { name, enabled:false, reason:typeof raw === 'string' ? raw : '当前运行时未报告支持' };
}

export function renderCapabilities(state) {
  const caps = state.snapshot?.capabilities ?? {};
  const rows = Object.entries(caps).map(([name, raw]) => normalize(name, raw));
  return h.heading('功能适配表', '只展示后端运行时实际报告的能力，不从页面静态推断支持。')
    + h.card('动态能力', h.table(['功能', '状态', '来源', '原因'], rows.map((item) => [LABELS[item.name] ?? item.name, html(h.tag(item.enabled ? '可用' : '不可用', item.enabled ? 'green' : 'amber')), item.source, item.enabled ? '' : item.reason]), '后端尚未报告任何能力。'))
    + h.card('明确边界', h.table(['能力', '状态'], [['图片 / 视频 / 音频', '仅在后端明确报告时开放'], ['Embedding', '仅在后端明确报告时开放'], ['多模型热加载', '仅在后端明确报告时开放'], ['oMLX 专属内核与缓存', '不映射为 TensorFold 成功状态']]));
}
