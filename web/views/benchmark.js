import { h, capability, formatNumber } from './shared.js';
import { jobDetails, renderJobActions } from './job-controls.js';
import { t } from '../i18n.js';

function jsonValue(value) {
  return value == null ? null : JSON.stringify(value);
}

function metricWithUnit(value, unit) {
  return value == null ? null : `${formatNumber(value)}${unit}`;
}

const BENCHMARK_PRESETS = Object.freeze({
  quick:{ prompt:'Summarize the benefits and tradeoffs of local inference in three bullet points.', max_tokens:64, runs:1 },
  standard:{ prompt:'Explain how prompt caching affects latency, throughput, and memory use. Include one practical example.', max_tokens:256, runs:3 },
  thorough:{ prompt:'Compare two approaches to serving a local language model, covering latency, throughput, memory, reliability, and operational tradeoffs.', max_tokens:512, runs:5 },
});

export function benchmarkRequest(tier, values = {}) {
  const preset = BENCHMARK_PRESETS[tier];
  if (!preset) throw new TypeError(t('请选择有效的测试档位'));
  const prompt = String(values.prompt ?? '').trim() || preset.prompt;
  const maxTokens = values.max_tokens === '' || values.max_tokens == null ? preset.max_tokens : Number(values.max_tokens);
  const runs = values.runs === '' || values.runs == null ? preset.runs : Number(values.runs);
  if (!prompt || !Number.isInteger(maxTokens) || maxTokens < 1 || !Number.isInteger(runs) || runs < 1 || runs > 20) {
    throw new TypeError(t('基准测试参数无效'));
  }
  return { prompt, max_tokens:maxTokens, runs };
}

export function renderBenchmark(state) {
  const data = state.pageData.benchmark ?? {};
  const results = data.results ?? data.items ?? [];
  const engineReady = ['ready', 'attached'].includes(state.snapshot?.engine?.state);
  const gate = capability(state.snapshot?.capabilities, 'benchmark');
  const disabledReason = !engineReady ? t('请先启动并等待引擎就绪') : (!gate.enabled ? gate.reason : '');
  const history = results.length ? results.map((result) => h.card(t('测试 {id}', { id:result.id ?? t('未采集') }), `<div class="tf-metrics compact">${h.metric('状态', result.status)}${h.metric('模型', result.model)}${h.metric('已完成', `${(result.results ?? []).length} / ${result.runs ?? t('未采集')}`)}${h.metric('错误', result.error)}</div><details><summary>${t('查看逐轮结果与参数')}</summary>${h.kv('时间', result.created_at)}${h.kv('引擎版本', result.engine_version)}${h.kv('提示词', result.prompt)}${h.kv('请求参数', jsonValue(result.parameters))}${h.kv('引擎参数', jsonValue(result.engine_parameters))}${h.table(['轮次', '状态', '输入 tokens', '输出 tokens', '总耗时', 'TTFT', 'Prefill', 'Decode', '错误'], (result.results ?? []).map((round, index) => [index + 1, round.status, round.input_tokens, round.output_tokens, metricWithUnit(round.elapsed, 's'), metricWithUnit(round.ttft, 's'), metricWithUnit(round.prefill_tps, ' tok/s'), metricWithUnit(round.decode_tps, ' tok/s'), round.error]))}</details>`)).join('') : `<div class="tf-empty">${t('暂无真实基准结果')}</div>`;
  const jobs = (state.snapshot?.jobs ?? []).filter(job => job.kind === 'benchmark' && ['running','queued','paused'].includes(job.status));
  const currentModel = state.snapshot?.engine?.model ?? '';
  return h.heading('基准测试', '选择测试档位，对当前就绪模型运行真实推理并查看结果。', h.button('刷新结果', 'load-page', 'benchmark'))
    + h.card('运行测试', `<form data-form="benchmark-run"><div class="tf-form-grid">${h.select('模型', 'model', [[currentModel, currentModel || t('未选择模型')]], currentModel)}${h.select('测试档位', 'tier', [['quick',t('快速')],['standard',t('标准')],['thorough',t('深入')]], 'quick')}</div><details class="tf-advanced"><summary>${t('高级参数')}</summary><div class="tf-form-grid">${h.textarea('提示词（留空使用档位预设）', 'prompt', '', { placeholder:'输入自定义测试提示词' })}${h.field('最大生成 tokens（留空使用预设）', 'max_tokens', '', { type:'number', min:1 })}${h.field('运行次数（留空使用预设）', 'runs', '', { type:'number', min:1, max:20 })}</div></details><div class="tf-actions form-actions">${h.button('运行', '', '', 'primary', disabledReason)}</div></form>`)
    + (jobs.length ? h.card('执行队列', jobs.map(job => `<div class="tf-download-job"><div class="tf-row"><div>${jobDetails(job)}</div><div class="tf-actions">${renderJobActions(job)}</div></div></div>`).join('')) : '')
    + h.card('结果历史', history);
}
