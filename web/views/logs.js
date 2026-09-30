import { h, escapeHtml } from './shared.js';
import { getLocale, t } from '../i18n.js';

export function renderLogs(state) {
  const data = state.pageData.logs ?? {};
  const entries = data.logs ?? data.items ?? [];
  const text = entries.map((entry) => {
    if (typeof entry === 'string') return entry;
    const timestamp = entry.at == null ? entry.time ?? entry.created_at : new Date(entry.at * 1000).toLocaleString(getLocale());
    return [timestamp, entry.level, entry.source, entry.message].filter((item) => item !== null && item !== undefined && item !== '').join(' ');
  }).join('\n');
  return h.compactHeading('运行日志', '后端统一脱敏后展示。', h.button('导出日志', 'logs-export'))
    + `<form class="tf-log-toolbar" data-form="logs-filter">${h.select('等级', 'level', [['',t('全部')],['debug','Debug'],['info','Info'],['warning','Warning'],['error','Error']], state.filters.logLevel)}${h.field('搜索', 'query', state.filters.logQuery)}${h.field('条数', 'limit', state.filters.logLimit, { type:'number', min:1, max:2000 })}<button type="submit" class="primary">${t('筛选')}</button></form>`
    + `<section class="tf-card tf-log-card"><pre class="tf-log">${entries.length ? escapeHtml(text) : escapeHtml(t('暂无日志'))}</pre></section>`;
}
