import { h, html } from './shared.js';

function average(rows, field) {
  const values = rows.map((row) => row[field]).filter((value) => typeof value === 'number' && Number.isFinite(value));
  return values.length ? values.reduce((sum, value) => sum + value, 0) / values.length : null;
}

export function renderStats(state) {
  const data = state.pageData.stats ?? state.snapshot?.stats ?? {};
  const rows = data.requests ?? data.items ?? [];
  const models = state.snapshot?.models ?? [];
  const total = data.total ?? {};
  const cancelled = total.cancelled ?? rows.filter((item) => item.status === 499 || item.status === 'cancelled').length;
  const failures = total.errors ?? rows.filter((item) => (typeof item.status === 'number' && item.status >= 400 && item.status !== 499) || item.status === 'failed').length;
  const requestCount = total.requests ?? data.requests_count ?? data.total_requests ?? rows.length;
  const successes = Math.max(0, requestCount - failures - cancelled);
  const compact = (value) => value == null ? null : JSON.stringify(value);
  return h.heading('统计与用量', '筛选真实网关请求记录；未采集字段保持“未采集”。', h.button('导出 CSV', 'stats-export'))
    + h.card('筛选', `<form data-form="stats-filter"><div class="tf-form-grid">${h.select('模型', 'model', [['', '全部模型'], ...models.map((model) => [model.id, model.name ?? model.id])], state.filters.statsModel)}${h.select('时间范围', 'range', [['24h', '最近 24 小时'], ['7d', '最近 7 天'], ['30d', '最近 30 天'], ['all', '全部']], state.filters.statsRange)}</div><div class="tf-actions form-actions"><button type="submit" class="primary">查询</button></div></form>`)
    + `<div class="tf-metrics">${h.metric('请求数', requestCount)}${h.metric('成功 / 失败 / 取消', `${successes} / ${failures} / ${cancelled}`, '后端聚合口径')}${h.metric('输入 tokens', total.input_tokens ?? data.input_tokens)}${h.metric('输出 tokens', total.output_tokens ?? data.output_tokens)}${h.metric('缓存 tokens', total.cache_tokens, 'usage.prompt_tokens_details.cached_tokens')}</div>`
    + `<div class="tf-metrics">${h.metric('平均总耗时', data.total?.avg_elapsed ?? average(rows, 'elapsed'), '秒')}${h.metric('平均 TTFT', data.total?.avg_ttft ?? average(rows, 'ttft'), '秒')}${h.metric('平均 Prefill', data.total?.avg_prefill_tps ?? average(rows, 'prefill_tps'), 'tok/s')}${h.metric('平均 Decode', data.total?.avg_decode_tps ?? average(rows, 'decode_tps'), 'tok/s')}</div>`
    + h.card('指标样本', h.kv('样本数', compact(total.metric_samples)))
    + h.card('各模型累计', h.table(['模型', '请求', '错误', '取消', '输入 tokens', '输出 tokens', '缓存 tokens', '平均耗时'], (data.models ?? []).map((model) => [model.model, model.requests, model.errors, model.cancelled, model.input_tokens, model.output_tokens, model.cache_tokens, model.avg_elapsed == null ? null : `${model.avg_elapsed}s`])))
    + h.card('请求记录', h.table(['时间', '模型', '状态', '总耗时', 'TTFT', 'Prefill', 'Decode', '输出', '缓存', '指标来源', '请求参数', '引擎参数', '错误'], rows.map((item) => [item.at, item.model, item.status, item.elapsed == null ? null : `${item.elapsed}s`, item.ttft == null ? null : `${item.ttft}s`, item.prefill_tps == null ? null : `${item.prefill_tps} tok/s`, item.decode_tps == null ? null : `${item.decode_tps} tok/s`, item.output_tokens, item.cache_tokens, compact({ ttft:item.ttft_source, prefill:item.prefill_tps_source }), compact(item.parameters), compact(item.engine_parameters), item.error])));
}
