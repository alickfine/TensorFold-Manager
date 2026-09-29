import { h } from './shared.js';

export const ADVANCED_OPTION_NAMES = ['drafter','drafter_bits','mtp_drafts','mtp_confidence','no_drafts','checkpoint_slots','spill_gib','max_snapshots','reasoning_effort','thinking_budget','name'];

export function renderAdvancedOptions(settings = {}) {
  const cliHint = '启动前由已安装引擎 CLI 验证；缺少对应参数时后端会阻止启动并返回原因。';
  return h.note(cliHint)
    + h.field('Drafter', 'drafter', settings.drafter ?? '', { hint:'auto、none、已安装仓库 ID 或绝对本地路径' })
    + h.select('Drafter bits', 'drafter_bits', [['','未设置'],['0','0'],['2','2'],['3','3'],['4','4'],['5','5'],['6','6'],['8','8']], settings.drafter_bits ?? '')
    + h.field('MTP drafts', 'mtp_drafts', settings.mtp_drafts ?? '', { type:'number', min:0, max:1024 })
    + h.field('MTP confidence', 'mtp_confidence', settings.mtp_confidence ?? '', { type:'number', min:0, max:1, step:0.01, disabled:true, hint:'CUDA-only；TensorFold MLX 后端明确不支持。' })
    + h.select('No drafts', 'no_drafts', [['','未设置'],['false','关闭'],['true','启用']], settings.no_drafts == null ? '' : String(settings.no_drafts))
    + h.field('Checkpoint slots', 'checkpoint_slots', settings.checkpoint_slots ?? '', { type:'number', min:0, max:4096 })
    + h.field('Spill GiB', 'spill_gib', settings.spill_gib ?? '', { type:'number', min:0, step:0.1 })
    + h.field('Max snapshots', 'max_snapshots', settings.max_snapshots ?? '', { type:'number', min:0, max:4096 })
    + h.select('Reasoning effort', 'reasoning_effort', [['','未设置'],['low','low'],['medium','medium'],['xhigh','xhigh']], settings.reasoning_effort ?? '')
    + h.field('Thinking budget', 'thinking_budget', settings.thinking_budget ?? '', { type:'number', min:0 })
    + h.field('服务模型名', 'name', settings.name ?? '', { hint:'OpenAI API 中报告的安全模型标识' });
}
