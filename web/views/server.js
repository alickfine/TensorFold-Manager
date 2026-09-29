import { h } from './shared.js';
import { t } from '../i18n.js';
import { renderJobActions } from './job-controls.js';

export function renderServer(state) {
  const settings = state.snapshot?.settings ?? {};
  const system = state.snapshot?.system ?? {};
  const jobs = (state.snapshot?.jobs ?? []).filter((job) => job.kind === 'model_discovery');
  const active = jobs.find((job) => ['queued', 'running', 'paused'].includes(job.status));
  const discovery = jobs.map((job) => {
    const progress = job.progress ?? {};
    const result = job.result ?? {};
    return `<div class="tf-download-job"><div class="tf-row"><div>${h.kv('状态', job.status)}${h.kv('扫描目录', progress.scanned_dirs ?? result.scanned_dirs)}${h.kv('发现模型', progress.found ?? result.models?.length)}${h.kv('阶段', progress.phase)}${h.kv('部分结果', result.partial)}${h.kv('扫描限制', result.limits?.join(', '))}${h.kv('新增目录', result.added_dirs?.join(', '))}${h.kv('跳过', result.skipped)}${h.kv('错误', job.error)}${result.partial ? h.note(t('扫描达到安全限制，当前结果不表示整盘扫描完成。'), true) : ''}</div><div class="tf-actions">${renderJobActions(job)}</div></div></div>`;
  }).join('');
  return h.heading('服务器与目录', '查看运行环境与模型目录，并由后端任务扫描本机磁盘。', h.button('扫描整台 Mac', 'models-discover', '', 'primary', active ? t('模型扫描正在进行') : ''))
    + `<div class="tf-grid two">${h.card('运行环境', `${h.kv('主机', system.hostname)}${h.kv('平台', system.platform)}${h.kv('架构', system.architecture ?? system.arch)}${h.kv('Python', system.python_version)}${h.kv('运行时目录', system.runtime_path)}`)}${h.card('进程边界', `${h.kv('管理实例', state.snapshot?.instance_id)}${h.kv('引擎 PID', state.snapshot?.engine?.pid)}${h.kv('引擎状态', state.snapshot?.engine?.state)}${h.note(t('App 自有生命周期由 Manager 管理；外部兼容只读接入；控制外部服务必须走已验证确认切换。'))}`)}</div>`
    + h.card('模型目录', h.form('settings-save',
      h.textarea('模型目录（每行一个）', 'model_dirs', (settings.model_dirs ?? []).join('\n'), { hint:'目录扫描只读；全盘扫描找到模型后由后端追加目录并重新扫描。' })
      + h.field('受管快照目录', 'snapshot_dir', settings.snapshot_dir ?? '', { full:true, disabled:true, hint:'安全边界固定为 App 拥有的快照根' }),
    '保存目录'))
    + h.card('全盘扫描任务', h.note(t('扫描检查上限为 180 秒；已登记模型目录总数最多 32 个。触发安全限制时会标为部分结果。')) + (discovery || `<div class="tf-empty">${t('尚未运行全盘模型扫描')}</div>`));
}
