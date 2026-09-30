import { h, html, escapeHtml } from './shared.js';
import { renderAdvancedOptions } from './advanced-options.js';
import { t } from '../i18n.js';

function resolveModel(state, modelId = '') {
  const models = state.snapshot?.models ?? [];
  const settings = state.snapshot?.settings ?? {};
  const requested = modelId || state.routeQuery?.get('model');
  const model = models.find((item) => item.id === requested) ?? models.find((item) => item.id === settings.selected_model) ?? models[0];
  return model;
}

export function renderModelConfigDialog(state, modelId = '') {
  const settings = state.snapshot?.settings ?? {};
  const model = resolveModel(state, modelId);
  const config = { ...settings, ...(model?.config ?? {}) };
  const profiles = state.snapshot?.profiles ?? state.pageData?.profiles?.profiles ?? [];
  if (!model) return h.note(t('请先扫描或下载受支持模型。'), true);
  return `<div class="tf-model-config-dialog">${h.note(t('保存模型级生成与推测解码参数；运行中的实例需重启后应用。'))}`
    + h.card(model.name ?? model.id, h.form('model-config-save',
      `<input type="hidden" name="model" value="${escapeHtml(model.id)}">`
      + h.field('上下文长度', 'context', config.context ?? '', { type:'number', min:1 })
      + h.field('最大生成 tokens', 'max_tokens', config.max_tokens ?? '', { type:'number', min:1 })
      + h.field('Temperature', 'temperature', config.temperature ?? '', { type:'number', min:0, step:'0.01' })
      + h.field('Top P', 'top_p', config.top_p ?? '', { type:'number', min:0, max:1, step:'0.01' })
      + h.field('Top K', 'top_k', config.top_k ?? '', { type:'number', min:0 })
      + h.select('Thinking', 'thinking', [['true', t('启用')], ['false', t('停用')]], String(Boolean(config.thinking)))
      + renderAdvancedOptions(config),
    '保存模型配置'), '', false)
    + h.card('配置档', `${h.note(t('应用目标：{model}。配置档没有模型元数据时不会猜测来源。', { model:model.name ?? model.id }))}${h.form('profile-create', h.field('名称', 'name', '', { required:true }) + `<input type="hidden" name="model" value="${escapeHtml(model.id)}">`, '保存当前配置为档案')}${h.table(['名称', '默认模型字段', '字段数', '操作'], profiles.map((profile) => [profile.name ?? profile.id, profile.config?.selected_model, Object.keys(profile.config ?? {}).length, html(`<div class="tf-actions">${h.button('应用到当前模型', 'profile-apply', profile.id, 'compact primary')}${h.button('导出', 'profile-export', profile.id, 'compact')}${h.button('删除', 'profile-delete', profile.id, 'compact danger')}</div>`)]))}`)
    + h.card('导入配置档', h.form('profile-import', h.textarea('配置档 JSON', 'json', '', { required:true, hint:'接受 {name,config} 或本页面导出的 {schema,profile}；未知字段会拒绝。' }), '校验并导入')) + '</div>';
}
