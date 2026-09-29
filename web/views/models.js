import { h, html, formatBytes } from './shared.js';

export function renderModels(state) {
  const models = state.snapshot?.models ?? [];
  const active = state.snapshot?.engine?.model;
  const ready = state.snapshot?.engine?.state === 'ready';
  return h.heading('模型库', '扫描配置目录并按运行时白名单展示兼容性，不猜测模型支持。', h.button('重新扫描', 'models-scan', '', 'primary'))
    + h.card('本机模型', h.table(['模型', '仓库 / 路径', '大小', '状态', '操作'], models.map((model) => {
      const reason = model.supported ? '' : (model.unsupported_reason ?? '当前运行时未报告支持');
      const isActive = active === model.id || active === model.repo;
      const lifecycleAction = ready ? 'engine-restart' : 'engine-start';
      return [model.name ?? model.id, model.repo ?? model.path, formatBytes(model.size_bytes), html(`${h.tag(model.installed ? '已安装' : '未安装', model.installed ? 'green' : '')} ${h.tag(model.supported ? '支持' : reason, model.supported ? 'blue' : 'amber')}`), html(`<div class="tf-actions">${h.button(isActive && ready ? '运行中' : ready ? '切换' : '启动', lifecycleAction, model.id, 'compact', isActive && ready ? '当前模型正在运行' : (!model.installed || !model.supported ? reason || '模型未安装' : ''))}${h.button('设为默认', 'model-default', model.id, 'compact')}${h.button('配置', 'goto', `model-config?model=${encodeURIComponent(model.id)}`, 'compact')}</div>`)]
    })));
}
