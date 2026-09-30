import { h, html, formatBytes } from './shared.js';
import { getLocale, t } from '../i18n.js';

function formatTimestamp(value) {
  if (value === null || value === undefined || value === '') return value;
  const numeric = Number(value);
  const parsed = Number.isFinite(numeric)
    ? new Date(Math.abs(numeric) < 1e12 ? numeric * 1000 : numeric)
    : new Date(value);
  return Number.isNaN(parsed.getTime()) ? value : parsed.toLocaleString(getLocale());
}

export function renderCache(state) {
  const cache = state.pageData.cache ?? {};
  const snapshot = state.snapshot ?? {};
  const running = snapshot.engine?.state !== 'stopped';
  const health = snapshot.engine?.health_detail && typeof snapshot.engine.health_detail === 'object'
    ? snapshot.engine.health_detail
    : snapshot.engine?.health && typeof snapshot.engine.health === 'object' ? snapshot.engine.health : {};
  const memory = health.memory ?? {};
  const settings = snapshot.settings ?? {};
  const stats = snapshot.stats ?? {};
  const gateway = snapshot.gateway ?? {};
  const memoryValue = (name) => formatBytes(memory[`${name}_bytes`] ?? memory[name]);
  const lastHealthAt = health.last_health_at ?? snapshot.engine?.last_health_at;
  const modelStats = stats.models ?? [];
  return h.heading('缓存管理', '只展示并清理 Manager 拥有且有 manifest 的快照。')
    + `<div class="tf-metrics">${h.metric('总占用', formatBytes(cache.size_bytes))}${h.metric('文件数量', cache.files)}${h.metric('后端确认归属', cache.owned)}${h.metric('允许清理', cache.can_clear)}</div>`
    + h.card('引擎内存与缓存', `<div class="tf-grid two"><div>${h.kv('Active', memoryValue('active'))}${h.kv('Cache', memoryValue('cache'))}${h.kv('Peak', memoryValue('peak'))}</div><div>${h.kv('Budget', memoryValue('budget'))}${h.kv('Footprint', memoryValue('footprint'))}${h.kv('Gateway cache tokens', stats.total?.cache_tokens)}${h.kv('最后健康采样', formatTimestamp(lastHealthAt))}${h.kv('健康采样错误', snapshot.engine?.health_error)}</div></div>${snapshot.engine?.state === 'attached' ? h.note(t('外部服务仅提供只读用量与请求统计；Manager 不扫描或清理该服务的缓存目录。')) : ''}`)
    + h.card('当前缓存配置', `${h.kv('Prompt cache GiB', settings.prompt_cache_gib)}${h.kv('MLX cache GiB', settings.mlx_cache_gib)}${h.kv('Snapshot 根', settings.snapshot_dir)}`)
    + h.card('各模型缓存统计', h.table(['模型', '请求', 'Cache tokens'], modelStats.map((model) => [model.model, model.requests, model.cache_tokens])))
    + h.card('受管快照根', `${h.kv('路径', cache.path)}${h.kv('归属', cache.owned)}${h.kv('不可清理原因', cache.reason)}`)
    + h.card('清理缓存', `${h.note(t('清理只作用于后端确认归属的快照，并要求引擎已停止。模型权重与外部目录不会被删除。'), true)}${h.button('清理受管快照', 'cache-clear', '', 'danger', running ? t('请先停止推理服务') : (!cache.can_clear ? cache.reason ?? t('后端未允许清理') : ''))}`);
}
