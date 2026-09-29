import { h, html, escapeHtml, formatBytes } from './shared.js';
import { jobDetails, renderJobActions } from './job-controls.js';
import { t } from '../i18n.js';
export function renderResources(resources = {}) {
 const memory=resources.memory ?? {};
 const missing=[...(resources.missing ?? []),...(memory.missing ?? [])];
 const services=resources.services ?? [];
 return h.card('内存与服务准入',`<div class="tf-metrics">${h.metric('物理内存',formatBytes(memory.physical_bytes))}${h.metric('可回收 / 可用内存',formatBytes(memory.available_bytes),'macOS 实际采样；不使用进程 RSS 估算')}${h.metric('内存压力',memory.pressure)}${h.metric('已用交换空间',formatBytes(memory.swap_used_bytes),'历史 swap 用量；不等同于当前内存压力')}</div>`
  + h.note(t('启动前重新采样并预留系统内存。兼容服务优先复用；切换时先释放旧模型，再核验端点退出和新模型预算。重任务串行执行。'))
  + (missing.length?h.note(t('采集信息不足，禁止加载新模型：{missing}', { missing:missing.join('、') }),true):'')
  + h.table(['已识别服务','PID','模型','监听端口','状态'],services.map(service=>[service.kind,service.pid,service.model_path,service.listening_ports?.join(', ') ?? service.port,service.health?.status]),'未发现当前用户的 TensorFold / oMLX 推理服务。'));
}
export function renderResourceReport(report = {}) {
 return renderResources(report.snapshot ?? {}) + h.card('准入结果',h.kv('允许启动',report.allowed)+h.kv('预估需求',formatBytes(report.estimate?.required_bytes))+h.kv('可分配上限',formatBytes(report.memory_limit_bytes))+h.kv('系统预留',formatBytes(report.system_reserve_bytes))+h.kv('阻断原因',report.blockers?.join('、'))+h.kv('缺失信息',report.missing?.join('、'))+h.note(t('模型预算为保守估计，并非实测峰值。')));
}

export function renderServiceControls(data = {}, models = [], jobs = [], engine = {}) {
 const ownPid = engine.control_owner === 'manager' ? engine.pid : null;
 const services = (data.services ?? []).filter(service => ownPid == null || String(service.pid) !== String(ownPid));
 const options = models.filter(model => model.installed && model.supported).map(model => [model.id, model.name ?? model.id]);
 const rows = services.map(service => {
  const supported = service.control?.supported === true && service.control?.action === 'stop_and_switch';
  const disabledReason = !supported ? service.control?.reason ?? t('后端未允许控制此服务') : !service.snapshot_id ? t('确认快照不可用，请刷新') : !options.length ? t('没有可启动的受支持目标模型') : '';
  const action = `<form data-form="service-switch" class="tf-inline-form"><input type="hidden" name="snapshot_id" value="${escapeHtml(service.snapshot_id ?? '')}">${h.select('目标模型','model',options,'',{hint:supported ? t('确认快照剩余 {seconds} 秒', { seconds:service.expires_in_seconds ?? 0 }) : disabledReason})}<button type="submit" class="danger"${disabledReason ? ` disabled title="${escapeHtml(disabledReason)}"` : ''}>${t('停止后切换')}</button></form>`;
  const health = typeof service.health === 'object' ? service.health?.status : service.health;
  return [service.kind, service.pid, service.executable, service.start_time, service.model_path, service.port, service.model_ids?.join(', '), health, html(action)];
 });
 const switchJobs = jobs.filter(job => job.kind === 'service_switch' && !['completed'].includes(job.status));
 return h.card('外部推理服务切换', h.note(t('控制仅使用 30 秒一次性进程实例快照。确认后先停止原实例，等待端点与内存释放，再启动目标；超时不会强杀。'), true)
  + h.table(['类型','PID','可执行文件','启动时间','模型路径','端口','模型 ID','健康','控制'], rows, '没有需要停止后切换的已识别服务。')
  + (switchJobs.length ? `<div class="tf-job-list">${switchJobs.map(job => `<div class="tf-download-job"><div class="tf-row"><div>${jobDetails(job)}</div><div class="tf-actions">${renderJobActions(job)}</div></div></div>`).join('')}</div>` : ''));
}
