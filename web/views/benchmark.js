import { h, capability } from './shared.js';
import { jobDetails, renderJobActions } from './job-controls.js';

function jsonValue(value) {
  return value == null ? null : JSON.stringify(value);
}

export function renderBenchmark(state) {
  const data = state.pageData.benchmark ?? {};
  const results = data.results ?? data.items ?? [];
  const engineReady = ['ready', 'attached'].includes(state.snapshot?.engine?.state);
  const gate = capability(state.snapshot?.capabilities, 'benchmark');
  const disabledReason = !engineReady ? '请先启动并等待引擎就绪' : (!gate.enabled ? gate.reason : '');
  const history = results.length ? results.map((result) => h.card(`测试 ${result.id ?? '未采集'}`, `${h.kv('时间', result.created_at)}${h.kv('状态', result.status)}${h.kv('模型', result.model)}${h.kv('引擎版本', result.engine_version)}${h.kv('提示词', result.prompt)}${h.kv('请求参数', jsonValue(result.parameters))}${h.kv('引擎参数', jsonValue(result.engine_parameters))}${h.kv('部分结果', `${(result.results ?? []).length} / ${result.runs ?? '未采集'}`)}${h.kv('错误', result.error)}${h.table(['轮次', '状态', '输入 tokens', '输出 tokens', '总耗时', 'TTFT', 'Prefill', 'Decode', '错误'], (result.results ?? []).map((round, index) => [index + 1, round.status, round.input_tokens, round.output_tokens, round.elapsed == null ? null : `${round.elapsed}s`, round.ttft == null ? null : `${round.ttft}s`, round.prefill_tps == null ? null : `${round.prefill_tps} tok/s`, round.decode_tps == null ? null : `${round.decode_tps} tok/s`, round.error]))}`)).join('') : '<div class="tf-empty">暂无真实基准结果</div>';
  const jobs = (state.snapshot?.jobs ?? []).filter(job => job.kind === 'benchmark' && ['running','queued','paused'].includes(job.status));
  return h.heading('基准测试', '提交真实推理任务并记录运行时、模型、tokens 与耗时。', h.button('刷新结果', 'load-page', 'benchmark'))
    + h.card('新建测试', `<form data-form="benchmark-run"><div class="tf-form-grid">${h.textarea('提示词', 'prompt', '', { required:true, placeholder:'输入真实测试提示词' })}${h.field('最大生成 tokens', 'max_tokens', state.snapshot?.settings?.max_tokens ?? 256, { type:'number', min:1, required:true })}${h.field('运行次数', 'runs', '1', { type:'number', min:1, max:20, required:true })}</div><div class="tf-actions form-actions">${h.button('开始测试', '', '', 'primary', disabledReason)}</div></form>`)
    + (jobs.length ? h.card('执行队列', jobs.map(job => `<div class="tf-download-job"><div class="tf-row"><div>${jobDetails(job)}</div><div class="tf-actions">${renderJobActions(job)}</div></div></div>`).join('')) : '')
    + h.card('结果历史', history);
}
