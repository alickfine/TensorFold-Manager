import { h, html, escapeHtml } from './shared.js';
import { t } from '../i18n.js';

export function renderUpdates(state) {
  const update = { ...(state.snapshot?.update ?? {}), ...(state.pageData.updates ?? {}) };
  const versions = update.latest ? [{ version:typeof update.latest === 'string' ? update.latest : update.latest.version, ...(typeof update.latest === 'object' ? update.latest : {}) }] : [];
  const engine = state.snapshot?.engine ?? {};
  const installJob = update.install_job;
  const upgradeJob = update.upgrade_job;
  const activationJob = update.activation_job;
  const blockers = update.blockers ?? [];
  const jobEvidence = (job) => job ? `${h.kv('任务 ID', job.id)}${h.kv('状态', job.status)}${h.kv('阶段', job.progress?.phase ?? job.phase)}${h.kv('错误', job.error)}${h.kv('结果', job.result == null ? null : JSON.stringify(job.result))}` : h.note(t('后端尚未报告任务证据'));
  const activeJob = [installJob, upgradeJob, activationJob].find((job) => ['queued','running','paused'].includes(job?.status));
  const targetVersion = typeof update.latest === 'string' ? update.latest : update.latest?.version;
  const upgradeDisabledReason = activeJob ? t('更新任务正在进行') : update.can_upgrade === false ? blockers.join(', ') || t('后端未允许升级') : '';
  const primaryAction = update.active
    ? h.button('升级引擎', 'update-upgrade', targetVersion ?? '', 'primary', upgradeDisabledReason)
    : h.button('安装引擎', 'engine-install', '', 'primary', activeJob ? t('更新任务正在进行') : '');
  return h.heading('版本与更新', '升级会保留当前可用环境，并展示后端返回的真实阶段、失败证据与可用动作。', h.button('检查更新', 'update-check') + primaryAction)
    + `<div class="tf-grid two">${h.card('当前版本', `${h.kv('Manager', state.snapshot?.app_version)}${h.kv('TensorFold', engine.version)}${h.kv('活动版本', update.active?.version)}${h.kv('活动 commit', update.active?.commit)}${h.kv('上次检查', update.checked_at)}`)}${h.card('候选状态', `${h.kv('候选版本', update.staged?.version)}${h.kv('候选 API 验证', update.staged?.api_verified)}${h.kv('上一版本', update.previous?.version)}${h.kv('阻碍', blockers.length ? blockers.join(', ') : null)}${h.kv('错误', update.error)}<div class="tf-actions">${update.previous ? h.button('回退', 'update-rollback', '', 'danger') : ''}${update.staged ? h.button('激活候选', 'update-activate', '', 'primary', update.can_activate === true ? '' : blockers.join(', ') || t('后端未允许激活')) : ''}</div>`)}</div>`
    + `<div class="tf-grid two">${h.card('安装任务证据', jobEvidence(installJob))}${h.card('升级任务证据', jobEvidence(upgradeJob))}${h.card('激活任务证据', jobEvidence(activationJob))}</div>`
    + h.card('最新官方版本', h.table(['版本', 'Commit', '来源', '操作'], versions.map((version) => [version.version ?? version.id, version.commit, update.release_url, html(h.button('安装候选', 'update-install', version.version ?? version.id, 'compact', version.pinned === false ? '只允许后端固定的官方版本' : ''))]), '未发现可安装候选。'))
    + h.card('官方版本说明',`<pre>${escapeHtml(update.notes ?? t('未采集'))}</pre>`);
}
