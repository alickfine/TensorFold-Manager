import { h, formatBytes } from './shared.js';
export function renderResources(resources = {}) {
 const memory=resources.memory ?? {};
 const missing=[...(resources.missing ?? []),...(memory.missing ?? [])];
 const services=resources.services ?? [];
 return h.card('内存与服务准入',`<div class="tf-metrics">${h.metric('物理内存',formatBytes(memory.physical_bytes))}${h.metric('可回收 / 可用内存',formatBytes(memory.available_bytes),'macOS 实际采样；不使用进程 RSS 估算')}${h.metric('内存压力',memory.pressure)}${h.metric('已用交换空间',formatBytes(memory.swap_used_bytes),'历史 swap 用量；不等同于当前内存压力')}</div>`
  + h.note('启动前重新采样并预留系统内存。兼容服务优先复用；切换时先释放旧模型，再核验端点退出和新模型预算。重任务串行执行。')
  + (missing.length?h.note(`采集信息不足，禁止加载新模型：${missing.join('、')}`,true):'')
  + h.table(['已识别服务','PID','模型','监听端口','状态'],services.map(service=>[service.kind,service.pid,service.model_path,service.listening_ports?.join(', ') ?? service.port,service.health?.status]),'未发现当前用户的 TensorFold / oMLX 推理服务。'));
}
export function renderResourceReport(report = {}) {
 return renderResources(report.snapshot ?? {}) + h.card('准入结果',h.kv('允许启动',report.allowed)+h.kv('预估需求',formatBytes(report.estimate?.required_bytes))+h.kv('可分配上限',formatBytes(report.memory_limit_bytes))+h.kv('系统预留',formatBytes(report.system_reserve_bytes))+h.kv('阻断原因',report.blockers?.join('、'))+h.kv('缺失信息',report.missing?.join('、'))+h.note('模型预算为保守估计，并非实测峰值。'));
}
