import { h, escapeHtml } from './shared.js';

export function renderLogs(state) {
  const data = state.pageData.logs ?? {};
  const entries = data.logs ?? data.items ?? [];
  const text = entries.map((entry) => {
    if (typeof entry === 'string') return entry;
    const timestamp = entry.at == null ? entry.time ?? entry.created_at : new Date(entry.at * 1000).toLocaleString();
    return [timestamp, entry.level, entry.source, entry.message].filter((item) => item !== null && item !== undefined && item !== '').join(' ');
  }).join('\n');
  return h.heading('运行日志', '后端统一脱敏后展示，支持等级与正文筛选。', h.button('导出日志', 'logs-export') + h.button('刷新', 'logs-filter'))
    + h.card('筛选', `<form data-form="logs-filter"><div class="tf-form-grid">${h.select('等级', 'level', [['','全部'],['debug','Debug'],['info','Info'],['warning','Warning'],['error','Error']], state.filters.logLevel)}${h.field('搜索', 'query', state.filters.logQuery)}${h.field('条数', 'limit', state.filters.logLimit, { type:'number', min:1, max:2000 })}</div><div class="tf-actions form-actions"><button type="submit" class="primary">应用筛选</button></div></form>`)
    + h.card('脱敏日志', entries.length ? `<pre class="tf-log">${escapeHtml(text)}</pre>` : '<div class="tf-empty">暂无日志</div>');
}
