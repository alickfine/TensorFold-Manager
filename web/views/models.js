import { h, html, formatBytes, escapeHtml } from './shared.js';
import { getLaunchGate } from './overview.js';
import { renderModelConfigDialog } from './model-config.js';
import { t } from '../i18n.js';

export function canValidateModel(model = {}) {
  return model.installed === true && model.supported !== true && typeof model.id === 'string' && model.id.startsWith('/');
}

export function renderModels(state) {
  const models = state.snapshot?.models ?? [];
  const active = state.snapshot?.engine?.model;
  const ready = state.snapshot?.engine?.state === 'ready';
  const attached = state.snapshot?.engine?.state === 'attached';
  const runtimeInstalled = Boolean(state.snapshot?.update?.active);
  const selected = models.find((model) => model.id === state.routeQuery?.get('model')) ?? models.find((model) => model.id === state.snapshot?.settings?.selected_model) ?? models[0];
  return h.heading('模型库', '扫描配置目录并按运行时白名单展示兼容性，不猜测模型支持。', `<div class="tf-actions">${!runtimeInstalled ? h.button('安装引擎 →', 'goto', 'updates') : ''}${h.button('重新扫描', 'models-scan', '', 'primary')}</div>`)
    + h.card('本机模型', h.table(['模型', '仓库 / 路径', '大小', '状态', '操作'], models.map((model) => {
      const catalogReason = model.supported ? '' : (model.unsupported_reason ?? t('当前运行时未报告支持'));
      const startReason = model.startable === true ? '' : (model.startable_reason ?? model.probe_error ?? t('尚未通过当前引擎检测'));
      const isActive = active === model.id || active === model.repo;
      const lifecycleAction = ready ? 'engine-restart' : 'engine-start';
      const gate = getLaunchGate(state.snapshot, model.id);
      const modelReason = !model.installed ? t('模型权重未完整安装') : model.startable !== true ? startReason : !gate.allowed ? gate.reason : '';
      const validation = model.validation;
      const lifecycle = attached
        ? h.button(isActive ? '已接入' : '需先断开', '', '', 'compact model-action', isActive ? t('当前外部服务只读接入') : t('请在总览断开外部服务，或使用已确认的停止后切换'))
        : h.button(isActive && ready ? '运行中' : ready ? '切换' : '启动', lifecycleAction, model.id, 'compact model-action', isActive && ready ? t('当前模型正在运行') : modelReason);
      return [model.name ?? model.id, model.repo ?? model.path, formatBytes(model.size_bytes), html(`${h.tag(t(model.installed ? '已安装' : '未安装'), model.installed ? 'green' : '')} ${h.tag(model.supported ? t('目录支持') : catalogReason, model.supported ? 'blue' : 'amber')} ${h.tag(model.startable === true ? t('可启动') : startReason, model.startable === true ? 'green' : 'amber')}${validation ? ` ${h.tag(t('CLI 兼容预检'), 'green')}` : ''}`), html(`<div class="tf-actions tf-model-actions">${canValidateModel(model) ? h.button('校验', 'model-validate', model.id, 'compact model-action', runtimeInstalled ? '' : t('请先安装 TensorFold 引擎')) : ''}${lifecycle}${h.button('默认', 'model-default', model.id, 'compact model-action', modelReason)}${h.button('配置', 'model-select', model.id, 'compact model-action')}</div>`)]
    })))
    + (selected ? `<section class="tf-inline-model-config"><div class="tf-row"><h2>${escapeHtml(t('模型配置'))} · ${escapeHtml(selected.name ?? selected.id)}</h2>${h.tag(selected.startable ? t('可启动') : t('尚未通过当前引擎检测'), selected.startable ? 'green' : 'amber')}</div>${renderModelConfigDialog(state, selected.id)}</section>` : '');
}
