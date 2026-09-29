import { h } from './shared.js';

export function renderEngineConfig(state) {
  const settings = state.snapshot?.settings ?? {};
  const engine = state.snapshot?.engine ?? {};
  return h.heading('推理框架配置', '只管理服务级资源参数；模型生成与推测解码参数在模型库的配置弹窗中编辑。')
    + h.card('运行时', `${h.kv('Engine Python', settings.engine_python)}${h.kv('TensorFold 版本', engine.version)}${h.kv('运行状态', engine.state)}`)
    + h.card('服务资源', h.form('settings-save',
      h.field('并发数', 'parallel', settings.parallel ?? '', { hint:'填写 auto 或 1–128 的整数' })
      + h.field('Prompt cache GiB', 'prompt_cache_gib', settings.prompt_cache_gib ?? '', { type:'number', min:0, step:'0.1' })
      + h.field('MLX cache GiB', 'mlx_cache_gib', settings.mlx_cache_gib ?? '', { type:'number', min:0, step:'0.1' })
      + h.field('Checkpoint slots', 'checkpoint_slots', settings.checkpoint_slots ?? '', { type:'number', min:0, max:4096 })
      + h.field('Spill GiB', 'spill_gib', settings.spill_gib ?? '', { type:'number', min:0, step:'0.1' })
      + h.field('Max snapshots', 'max_snapshots', settings.max_snapshots ?? '', { type:'number', min:0, max:4096 }),
    '保存框架配置'));
}
