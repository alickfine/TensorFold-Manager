import { h, html, formatBytes } from './shared.js';

export function renderCache(state) {
  const cache = state.pageData.cache ?? {};
  const running = state.snapshot?.engine?.state !== 'stopped';
  return h.heading('缓存管理', '只展示并清理 Manager 拥有且有 manifest 的快照。', h.button('刷新', 'load-page', 'cache'))
    + `<div class="tf-metrics">${h.metric('总占用', formatBytes(cache.size_bytes))}${h.metric('文件数量', cache.files)}${h.metric('后端确认归属', cache.owned)}${h.metric('允许清理', cache.can_clear)}</div>`
    + h.card('受管快照根', `${h.kv('路径', cache.path)}${h.kv('归属', cache.owned)}${h.kv('不可清理原因', cache.reason)}`)
    + h.card('清理缓存', `${h.note('清理只作用于后端确认归属的快照，并要求引擎已停止。模型权重与外部目录不会被删除。', true)}${h.button('清理受管快照', 'cache-clear', '', 'danger', running ? '请先停止推理服务' : (!cache.can_clear ? cache.reason ?? '后端未允许清理' : ''))}`);
}
