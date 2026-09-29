import { h, capability } from './shared.js';

export function renderApi(state) {
  const settings = state.snapshot?.settings ?? {};
  const caps = state.snapshot?.capabilities ?? {};
  const gateway = `http://127.0.0.1:${settings.gateway_port ?? '未采集'}/v1`;
  const features = [
    ['Chat Completions', capability(caps, 'chat')],
    ['Text Completions', capability(caps, 'completions')],
    ['SSE 流式输出', capability(caps, 'streaming')],
    ['Tool calling', capability(caps, 'tool_calling')],
  ];
  return h.heading('API 与集成', 'OpenAI 兼容网关使用单独签发的 API Key。管理令牌不会显示或复制。')
    + h.card('端点', `${h.kv('Base URL', gateway)}${h.kv('Models', `${gateway}/models`)}${h.kv('Chat Completions', `${gateway}/chat/completions`)}${h.note('网关默认仅监听 loopback。客户端密钥请在“认证与密钥”创建。')}`)
    + h.card('运行时能力', h.table(['能力', '状态', '原因'], features.map(([name, item]) => [name, item.enabled ? '支持' : '不可用', item.enabled ? '' : item.reason])));
}
