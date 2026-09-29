import { h, capability, formatBytes, escapeHtml } from './shared.js';
import { jobDetails, renderJobActions } from './job-controls.js';

const PROVIDERS = [
  ['hf-download', 'Hugging Face 下载'],
  ['hf-upload', 'Hugging Face 上传'],
  ['modelscope-download', 'ModelScope 下载'],
];

function credentialCards(credentials = {}) {
  const providers = credentials.providers ?? {};
  const unavailable = credentials.unavailable_reason ?? '';
  return PROVIDERS.map(([id, label]) => {
    const status = providers[id] ?? { provider:id, configured:false };
    const form = `<form data-form="credential-save"><input type="hidden" name="provider" value="${escapeHtml(id)}"><div class="tf-form-grid">${h.field('凭据', 'token', '', { type:'password', required:true, disabled:Boolean(unavailable), hint:unavailable || '仅交给系统凭据助手；页面不会回填或持久化明文' })}</div><div class="tf-actions form-actions"><button type="submit" class="primary"${unavailable ? ` disabled title="${escapeHtml(unavailable)}"` : ''}>${status.configured ? '替换' : '配置'}</button>${status.configured ? h.button('删除', 'credential-delete', id, 'danger', unavailable) : ''}</div></form>`;
    return h.card(label, `${h.kv('状态', status.configured ? '已配置' : '未配置')}${form}`);
  }).join('');
}

function uploadPlan(plan) {
  if (!plan) return '';
  const publicNew = plan.visibility === 'public' && !plan.existing;
  return h.card('上传确认预览', `${h.note(publicNew ? '新建公开仓库：确认后会把所列文件公开发布。' : `确认后上传到${plan.existing ? '现有' : '新建'}${plan.visibility === 'public' ? '公开' : '私有'}仓库。`, true)}${h.kv('仓库', plan.repo)}${h.kv('实际可见性', plan.visibility)}${h.kv('远端现状', plan.existing ? `已存在 · ${plan.remote_visibility ?? plan.visibility}` : '尚不存在')}${h.kv('文件数', plan.files?.length)}${h.kv('总大小', formatBytes(plan.size_bytes))}${h.table(['文件','大小','SHA256'], (plan.files ?? []).map(file => [file.path, formatBytes(file.size_bytes), file.sha256]))}${h.button(publicNew ? '确认新建公开仓库并上传' : '确认上传', 'upload-confirm', plan.plan_id, 'danger')}`);
}

export function renderModelTools(state) {
  const caps = state.snapshot?.capabilities ?? {};
  const quantize = capability(caps, 'quantize');
  const upload = capability(caps, 'upload');
  const tools = state.pageData.tools ?? {};
  const active = tools.active;
  const models = (state.snapshot?.models ?? []).filter(model => model.installed);
  const modelOptions = models.map(model => [model.id, model.name ?? model.id]);
  const jobs = (state.snapshot?.jobs ?? []).filter(job => ['tool_install','quantize','upload'].includes(job.kind));
  const quantizeForm = quantize.enabled ? h.form('tool-quantize',
    h.select('源模型', 'model', modelOptions, '')
    + h.field('输出名称', 'name', '', { hint:'留空时由后端使用安全名称；输出固定在 App 受管目录' })
    + h.select('量化位宽', 'bits', [['2','2 bit'],['3','3 bit'],['4','4 bit'],['6','6 bit'],['8','8 bit']], '4')
    + h.select('Group size', 'group_size', [['32','32'],['64','64'],['128','128']], '64')
    + `<input type="hidden" name="mode" value="affine">${h.kv('量化模式', 'affine')}`,
    '创建量化任务') : h.button('量化不可用', '', '', '', quantize.reason);
  const uploadForm = upload.enabled ? h.form('tool-upload-prepare',
    h.select('受管模型', 'model', modelOptions, '')
    + h.field('目标仓库', 'repo', '', { required:true, hint:'精确 owner/model' })
    + h.select('请求可见性', 'visibility', [['private','私有'],['public','公开']], 'private'),
    '准备上传预览') : h.button('上传不可用', '', '', '', upload.reason);
  const taskList = jobs.length ? jobs.map(job => `<div class="tf-download-job"><div class="tf-row"><div>${jobDetails(job)}</div><div class="tf-actions">${renderJobActions(job)}</div></div></div>`).join('') : '<div class="tf-empty">暂无工具任务</div>';
  return h.heading('量化与上传', '工具运行时隔离安装；上传必须先读取远端实际可见性并生成文件预览。', h.button('刷新', 'load-page', 'model-tools'))
    + h.card('工具运行时', `${h.kv('状态', active ? '已安装' : '未安装')}${h.kv('安装时间', active?.installed_at)}${h.kv('后端固定版本', Object.entries(tools.pins ?? {}).map(([name, version]) => `${name} ${version}`).join(' · ') || null)}${h.kv('实际包版本', Object.entries(active?.packages ?? {}).map(([name, version]) => `${name} ${version}`).join(' · ') || null)}${!active ? h.button('安装模型工具', 'tool-install', '', 'primary', jobs.some(job => job.kind === 'tool_install' && ['queued','running'].includes(job.status)) ? '安装任务进行中' : '') : ''}`)
    + h.card('任务状态', taskList)
    + h.card('应用凭据', h.note('配置接口只返回 configured 状态；密码输入不会写入页面状态或本地存储。') + `<div class="tf-grid three">${credentialCards(state.pageData.credentials)}</div>`)
    + `<div class="tf-grid two">${h.card('标准 MLX 量化', `${h.note(quantize.enabled ? '仅 affine；开始前重新执行资源与服务门禁。' : quantize.reason, !quantize.enabled)}${quantizeForm}`)}${h.card('Hugging Face 上传', `${h.note(upload.enabled ? '准备步骤会读取远端实际可见性并计算文件列表和摘要；此时不会上传。' : upload.reason, true)}${uploadForm}`)}</div>`
    + uploadPlan(state.pageData.uploadPlan);
}
