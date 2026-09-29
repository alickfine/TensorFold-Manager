import { h, html } from './shared.js';

export function renderStats(state) {
  const data = state.pageData.stats ?? state.snapshot?.stats ?? {};
  const rows = data.requests ?? data.items ?? [];
  const models = state.snapshot?.models ?? [];
  return h.heading('统计与用量', '筛选真实网关请求记录；未采集字段保持“未采集”。', h.button('导出 CSV', 'stats-export'))
    + h.card('筛选', `<form data-form="stats-filter"><div class="tf-form-grid">${h.select('模型', 'model', [['', '全部模型'], ...models.map((model) => [model.id, model.name ?? model.id])], state.filters.statsModel)}${h.select('时间范围', 'range', [['24h', '最近 24 小时'], ['7d', '最近 7 天'], ['30d', '最近 30 天'], ['all', '全部']], state.filters.statsRange)}</div><div class="tf-actions form-actions"><button type="submit" class="primary">查询</button></div></form>`)
    + `<div class="tf-metrics">${h.metric('请求数', data.total?.requests ?? data.requests_count ?? data.total_requests)}${h.metric('输入 tokens', data.total?.input_tokens ?? data.input_tokens)}${h.metric('输出 tokens', data.total?.output_tokens ?? data.output_tokens)}${h.metric('错误数', data.total?.errors ?? data.errors)}</div>`
    + h.card('请求记录', h.table(['时间', '模型', '状态', '总耗时', 'TTFT', 'Decode', 'Tokens'], rows.map((item) => [item.at, item.model, item.status, item.elapsed == null ? null : `${item.elapsed}s`, item.ttft == null ? null : `${item.ttft}s`, item.decode_tps == null ? null : `${item.decode_tps} tok/s`, item.output_tokens])));
}
