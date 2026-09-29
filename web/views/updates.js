import { h, html, escapeHtml } from './shared.js';
import { t } from '../i18n.js';

export function renderUpdates(state) {
  const update = state.pageData.updates ?? state.snapshot?.update ?? {};
  const versions = update.latest ? [{ version:typeof update.latest === 'string' ? update.latest : update.latest.version, ...(typeof update.latest === 'object' ? update.latest : {}) }] : [];
  const engine = state.snapshot?.engine ?? {};
  return h.heading('版本与更新', '候选安装在隔离环境，验证通过后才可激活；失败保留旧环境。', h.button('检查更新', 'update-check', '', 'primary'))
    + `<div class="tf-grid two">${h.card('当前版本', `${h.kv('Manager', state.snapshot?.app_version)}${h.kv('TensorFold', engine.version)}${h.kv('活动版本', update.active?.version)}${h.kv('活动 commit', update.active?.commit)}${h.kv('上次检查', update.checked_at)}${h.button('安装官方引擎', 'engine-install', '', '', update.installing ? '安装任务进行中' : '')}`)}${h.card('更新状态', `${h.kv('候选版本', update.staged?.version)}${h.kv('候选 API 验证', update.staged?.api_verified)}${h.kv('上一版本', update.previous?.version)}${h.kv('错误', update.error)}${update.previous ? h.button('回退', 'update-rollback', '', 'danger') : ''}${update.staged ? h.button('激活候选', 'update-activate', '', 'primary') : ''}`)}</div>`
    + h.card('最新官方版本', h.table(['版本', 'Commit', '来源', '操作'], versions.map((version) => [version.version ?? version.id, version.commit, update.release_url, html(h.button('安装候选', 'update-install', version.version ?? version.id, 'compact', version.pinned === false ? '只允许后端固定的官方版本' : ''))]), '未发现可安装候选。'))
    + h.card('官方版本说明',`<pre>${escapeHtml(update.notes ?? t('未采集'))}</pre>`);
}
