import { h, escapeHtml, capability } from './shared.js';

function messages(items) {
  if (!items?.length) return '<div class="tf-empty">开始一段真实本机对话</div>';
  return items.map((message) => `<div class="tf-message"><div class="tf-avatar">${message.role === 'assistant' ? 'TF' : '你'}</div><div class="tf-message-body">${escapeHtml(message.content ?? '')}</div></div>`).join('');
}

export function renderChat(state) {
  const settings = state.snapshot?.settings ?? {};
  const ready = state.snapshot?.engine?.state === 'ready';
  const chatGate = capability(state.snapshot?.capabilities, 'chat');
  const streamGate = capability(state.snapshot?.capabilities, 'streaming');
  const disabledReason = !ready ? '引擎尚未就绪' : !chatGate.enabled ? chatGate.reason : !streamGate.enabled ? streamGate.reason : '';
  return h.heading('内置聊天', '通过受认证的管理代理调用当前 TensorFold，并保存本地历史。', h.button('新建对话', 'chat-new'))
    + `<div class="tf-chat-layout"><section class="tf-chat-main"><div id="chat-messages" class="tf-messages">${messages(state.chat.messages)}</div><form class="tf-composer" data-form="chat-send"><label class="sr-only" for="chat-input">消息</label><textarea id="chat-input" name="message" placeholder="输入消息" required></textarea><div class="tf-row"><span class="tf-sub">${escapeHtml(state.snapshot?.engine?.model ?? '未选择模型')}</span><div class="tf-actions">${state.chat.streaming ? h.button('停止生成', 'chat-abort', '', 'danger') : h.button('发送', '', '', 'primary', disabledReason)}</div></div></form></section><aside class="tf-chat-settings"><h2>生成设置</h2>${h.kv('模型', state.snapshot?.engine?.model)}${h.kv('Temperature', settings.temperature)}${h.kv('Top P', settings.top_p)}${h.kv('最大 tokens', settings.max_tokens)}${h.note(disabledReason || '停止生成会中断当前网络请求，并把已收到内容保留为取消结果。', Boolean(disabledReason))}</aside></div>`;
}
