import { renderModels } from './models.js';
import { renderDownloads } from './downloads.js';
import { escapeHtml, h } from './shared.js';
import { t } from '../i18n.js';

export function filterModels(models = [], query = '') {
  const needle = String(query).trim().normalize('NFKC').toLocaleLowerCase();
  if (!needle) return models.slice();
  return models.filter((model) => [model.name, model.repo, model.path, model.id]
    .some((value) => String(value ?? '').normalize('NFKC').toLocaleLowerCase().includes(needle)));
}

export function renderModelWorkspace(state) {
  const section = state.routeQuery?.get('section') === 'downloads' ? 'downloads' : 'library';
  const tabs = `<div class="tf-section-tabs" role="tablist"><button data-action="section" data-value="models:library" class="${section === 'library' ? 'active' : ''}" role="tab" aria-selected="${section === 'library'}">${escapeHtml(t('模型库'))}</button><button data-action="section" data-value="models:downloads" class="${section === 'downloads' ? 'active' : ''}" role="tab" aria-selected="${section === 'downloads'}">${escapeHtml(t('模型下载器'))}</button></div>`;
  const body = section === 'downloads' ? renderDownloads(state) : renderModels(state, filterModels(state.snapshot?.models, state.modelSearch));
  return `<div class="tf-model-workspace">${h.compactHeading('模型库', '本机模型、配置和受支持下载。')}${tabs}<div class="tf-composed-section">${body.replaceAll('<h1>', '<h2>').replaceAll('</h1>', '</h2>')}</div></div>`;
}
