import { renderEngineConfig } from './engine-config.js';
import { renderServer } from './server.js';
import { renderCache } from './cache.js';
import { renderApi } from './api-integration.js';
import { renderUpdates } from './updates.js';
import { h, escapeHtml } from './shared.js';
import { t } from '../i18n.js';

const sections = [
  ['runtime', '运行与目录'],
  ['storage', '存储与缓存'],
  ['api', 'API 与密钥'],
  ['updates', '版本与更新'],
];

export function renderWorkspaceSettings(state) {
  const selected = sections.some(([id]) => id === state.routeQuery?.get('section')) ? state.routeQuery.get('section') : 'runtime';
  const content = selected === 'runtime' ? renderEngineConfig(state) + renderServer(state)
    : selected === 'storage' ? renderCache(state)
    : selected === 'api' ? renderApi(state)
    : renderUpdates(state);
  return h.heading('设置', '按任务集中查看状态和修改配置。')
    + `<div class="tf-section-tabs" role="tablist">${sections.map(([id,label]) => `<button data-action="section" data-value="settings:${id}" class="${id === selected ? 'active' : ''}" role="tab" aria-selected="${id === selected}">${escapeHtml(t(label))}</button>`).join('')}</div>`
    + `<div class="tf-composed-section">${content}</div>`;
}
