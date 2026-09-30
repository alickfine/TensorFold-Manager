import { renderLogs } from './logs.js';
import { renderBenchmark } from './benchmark.js';
import { h, escapeHtml } from './shared.js';
import { t } from '../i18n.js';

export function renderActivity(state) {
  const section = state.routeQuery?.get('section') === 'benchmark' ? 'benchmark' : 'logs';
  const content = section === 'logs' ? renderLogs(state) : renderBenchmark(state);
  return h.heading('活动', '查看运行日志与真实基准结果。')
    + `<div class="tf-section-tabs" role="tablist"><button data-action="section" data-value="activity:logs" class="${section === 'logs' ? 'active' : ''}" role="tab" aria-selected="${section === 'logs'}">${escapeHtml(t('运行日志'))}</button><button data-action="section" data-value="activity:benchmark" class="${section === 'benchmark' ? 'active' : ''}" role="tab" aria-selected="${section === 'benchmark'}">${escapeHtml(t('基准测试'))}</button></div>`
    + (section === 'benchmark' ? h.note(t('基准测试只对当前就绪模型发起请求，不会停止或卸载其他模型。')) : '')
    + `<div class="tf-composed-section">${content.replaceAll('<h1>', '<h2>').replaceAll('</h1>', '</h2>')}</div>`;
}
