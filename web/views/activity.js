import { renderLogs } from './logs.js';
import { renderBenchmark } from './benchmark.js';
import { h, escapeHtml } from './shared.js';
import { t } from '../i18n.js';

export function renderActivity(state) {
  const section = state.routeQuery?.get('section') === 'benchmark' ? 'benchmark' : 'logs';
  return h.heading('活动', '查看运行日志与真实基准结果。')
    + `<div class="tf-section-tabs" role="tablist"><button data-action="section" data-value="activity:logs" class="${section === 'logs' ? 'active' : ''}" role="tab" aria-selected="${section === 'logs'}">${escapeHtml(t('运行日志'))}</button><button data-action="section" data-value="activity:benchmark" class="${section === 'benchmark' ? 'active' : ''}" role="tab" aria-selected="${section === 'benchmark'}">${escapeHtml(t('基准测试'))}</button></div>`
    + `<div class="tf-composed-section">${section === 'logs' ? renderLogs(state) : renderBenchmark(state)}</div>`;
}
