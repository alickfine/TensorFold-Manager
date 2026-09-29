import { h, capability } from './shared.js';

export function renderBenchmark(state) {
  const data = state.pageData.benchmark ?? {};
  const results = data.results ?? data.items ?? [];
  const engineReady = state.snapshot?.engine?.state === 'ready';
  const gate = capability(state.snapshot?.capabilities, 'benchmark');
  const disabledReason = !engineReady ? '请先启动并等待引擎就绪' : (!gate.enabled ? gate.reason : '');
  return h.heading('基准测试', '提交真实推理任务并记录运行时、模型、tokens 与耗时。', h.button('刷新结果', 'load-page', 'benchmark'))
    + h.card('新建测试', `<form data-form="benchmark-run"><div class="tf-form-grid">${h.textarea('提示词', 'prompt', '', { required:true, placeholder:'输入真实测试提示词' })}${h.field('最大生成 tokens', 'max_tokens', state.snapshot?.settings?.max_tokens ?? 256, { type:'number', min:1, required:true })}${h.field('运行次数', 'runs', '1', { type:'number', min:1, max:20, required:true })}</div><div class="tf-actions form-actions">${h.button('开始测试', '', '', 'primary', disabledReason)}</div></form>`)
    + h.card('结果历史', h.table(['时间', '提示词', '最大 tokens', '次数', '完成结果'], results.map((result) => [result.created_at, result.prompt, result.max_tokens, result.runs, result.results?.length])));
}
