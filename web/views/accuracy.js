import { h, html, capability } from './shared.js';
import { jobDetails, renderJobActions } from './job-controls.js';
export function renderAccuracy(state) {
 const data=state.pageData.accuracy ?? {};
 const cases=data.cases ?? []; const results=data.results ?? [];
 const ready=['ready','attached'].includes(state.snapshot?.engine?.state);
 const gate=capability(state.snapshot?.capabilities,'accuracy');
 const reason=!cases.length?'请先添加参考测试':!ready?'请先等待推理服务就绪':!gate.enabled?gate.reason:'';
 const jobs=(state.snapshot?.jobs ?? []).filter(job=>job.kind==='accuracy' && ['running','queued','paused'].includes(job.status));
 return h.heading('参考答案测试','使用你提供的题目和参考答案验证真实模型输出。',h.button('刷新结果','load-page','accuracy'))
  + h.note('评分为参考答案一致性：完全相等或包含参考文本，不代表模型的通用知识准确率。temperature 固定为 0；思考关闭。')
  + h.card('测试题目',h.table(['名称','提示词','参考答案','匹配规则','生成上限','操作'],cases.map(item=>[item.name,item.prompt,item.expected,item.match==='exact'?'完全相等':'包含参考文本',item.max_tokens,html(h.button('删除','accuracy-delete',item.id,'compact'))]),'尚无题目，请先添加参考测试。'),h.button('运行全部','accuracy-run','','primary',reason))
  + h.card('添加题目',h.form('accuracy-add',h.field('名称','name','',{required:true})+h.select('匹配规则','match',[['exact','完全相等'],['contains','包含参考文本']],'exact')+h.field('生成上限','max_tokens',256,{type:'number',min:1,max:32768,required:true})+h.textarea('提示词','prompt','',{required:true})+h.textarea('参考答案','expected','',{required:true}),'添加测试'))
  + (jobs.length?h.card('运行队列',h.table(['任务','状态','参数与进度','操作'],jobs.map(job=>[job.id,job.status,html(jobDetails(job)),html(renderJobActions(job))]))):'')
  + h.card('真实结果',results.length?results.map(result=>h.card(`测试 ${result.id}`,h.kv('状态',result.status)+h.kv('完成题数',`${result.completed} / ${result.total}`)+h.kv('通过题数',result.passed)+h.kv('已完成题的一致性',result.agreement_rate==null?null:`${(result.agreement_rate*100).toFixed(1)}%`)+h.kv('模型',result.model)+h.kv('引擎版本',result.engine_version)+(result.error?h.note(result.error,true):'')+h.table(['题目','参考文本','实际输出','结果','输出 tokens'],(result.results ?? []).map(row=>[row.case?.name,row.case?.expected,row.output,row.passed?'通过':'不一致',row.metrics?.output_tokens])))).join(''):'<div class="tf-empty">尚无参考测试结果</div>',h.button('清空结果','accuracy-reset','','',jobs.length?'先取消正在执行的参考测试':''));
}
