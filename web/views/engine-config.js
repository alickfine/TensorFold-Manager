import { h, capability } from './shared.js';
import { renderAdvancedOptions } from './advanced-options.js';
import { t } from '../i18n.js';

export function renderEngineConfig(state) {
  const settings = state.snapshot?.settings ?? {};
  const external = capability(state.snapshot?.capabilities, 'external_engine_python');
  return h.heading('推理框架配置', '编辑持久化默认值；页面只提交协议允许的字段。')
    + h.card('推理参数', h.form('settings-save',
      h.field('上下文长度', 'context', settings.context ?? '', { type:'number', min:1 })
      + h.field('最大生成 tokens', 'max_tokens', settings.max_tokens ?? '', { type:'number', min:1 })
      + h.field('Temperature', 'temperature', settings.temperature ?? '', { type:'number', min:0, step:'0.01' })
      + h.field('Top P', 'top_p', settings.top_p ?? '', { type:'number', min:0, max:1, step:'0.01' })
      + h.field('Top K', 'top_k', settings.top_k ?? '', { type:'number', min:0 })
      + h.field('并发数', 'parallel', settings.parallel ?? '', { hint:'填写 auto 或 1–128 的整数' })
      + h.select('Thinking', 'thinking', [['true',t('启用')],['false',t('停用')]], String(Boolean(settings.thinking)))
      + h.field('Prompt cache GiB', 'prompt_cache_gib', settings.prompt_cache_gib ?? '', { type:'number', min:0, step:'0.1' })
      + h.field('MLX cache GiB', 'mlx_cache_gib', settings.mlx_cache_gib ?? '', { type:'number', min:0, step:'0.1' })
      + h.field('Engine Python', 'engine_python', settings.engine_python ?? '', { disabled:!external.enabled, hint:external.enabled ? '仅显式开发模式可更改' : external.reason }),
    '保存配置'))
    + h.card('高级参数', h.form('settings-save', renderAdvancedOptions(settings), '保存高级配置'));
}
