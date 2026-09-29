import { h, capability } from './shared.js';

export function renderModelTools(state) {
  const caps = state.snapshot?.capabilities ?? {};
  const quantize = capability(caps, 'quantize');
  const upload = capability(caps, 'upload');
  const models = (state.snapshot?.models ?? []).filter((model) => model.installed);
  const modelOptions = models.map((model) => [model.id, model.name ?? model.id]);
  const quantizeForm = quantize.enabled ? h.form('tool-quantize', h.select('源模型', 'model', modelOptions, '') + h.field('输出目录', 'directory', '', { required:true }) + h.select('量化位宽', 'bits', [['4','4 bit'],['6','6 bit'],['8','8 bit']], '4'), '创建量化任务') : h.button('量化不可用', '', '', '', quantize.reason);
  const uploadForm = upload.enabled ? h.form('tool-upload', h.field('受管模型路径', 'path', '', { required:true }) + h.field('目标仓库', 'repo', '', { required:true }) + h.select('可见性', 'visibility', [['private','私有'],['public','公开']], 'private'), '创建上传任务') : h.button('上传不可用', '', '', '', upload.reason);
  return h.heading('量化与上传', '后端能力预检通过后才开放任务入口；提交并不表示处理成功。')
    + `<div class="tf-grid two">${h.card('量化', `${h.note(quantize.enabled ? '运行时已报告量化能力；输出仍需独立兼容性校验。' : quantize.reason, !quantize.enabled)}${quantizeForm}`)}${h.card('上传', `${h.note(upload.enabled ? '上传属于外部写入；确认目标仓库和可见性后由后端执行。' : upload.reason, true)}${uploadForm}`)}</div>`;
}
