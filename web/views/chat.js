import { h, escapeHtml, capability } from './shared.js';
import { parseChatOptions } from '../chat-options.js';
import { t } from '../i18n.js';

function messages(items) {
  if (!items?.length) return `<div class="tf-empty">${t('开始一段真实本机对话')}</div>`;
  return items.map((message) => `<div class="tf-message"><div class="tf-avatar">${message.role === 'assistant' ? 'TF' : t('你')}</div><div><div class="tf-message-body">${escapeHtml(message.content ?? '')}</div>${message.reasoning ? `<details><summary>${t('思考过程')}</summary><pre>${escapeHtml(message.reasoning)}</pre></details>` : ''}${message.tool_calls?.length ? `<details open><summary>${t('工具调用（仅展示，未执行）')}</summary><pre>${escapeHtml(JSON.stringify(message.tool_calls,null,2))}</pre></details>` : ''}${message.metrics ? `<div class="tf-sub">${escapeHtml(message.status ?? 'completed')} · ${t('浏览器耗时')} ${Number(message.metrics.elapsed_seconds ?? 0).toFixed(2)}s · ${escapeHtml(message.metrics.completion_tokens ?? t('未采集'))} tokens · ${escapeHtml(message.metrics.tokens_per_second ?? t('未采集'))} tok/s</div>` : ''}</div></div>`).join('');
}

export function renderChat(state) {
  const settings = state.snapshot?.settings ?? {};
  const options = parseChatOptions(state.chat.options ?? {},settings);
  const ready = ['ready', 'attached'].includes(state.snapshot?.engine?.state);
  const chatGate = capability(state.snapshot?.capabilities, 'chat');
  const streamGate = capability(state.snapshot?.capabilities, 'streaming');
  const disabledReason = !ready ? t('引擎尚未就绪') : !chatGate.enabled ? chatGate.reason : !streamGate.enabled ? streamGate.reason : '';
  return h.heading('内置聊天', '通过受认证的管理代理调用当前 TensorFold，并保存本地历史。', h.button('导出 JSON', 'chat-export')+h.button('新建对话', 'chat-new'))
    + `<div class="tf-chat-layout"><section class="tf-chat-main"><div id="chat-messages" class="tf-messages">${messages(state.chat.messages)}</div><form class="tf-composer" data-form="chat-send"><label class="sr-only" for="chat-input">${t('消息')}</label><textarea id="chat-input" name="message" placeholder="${t('输入消息')}" required></textarea><div class="tf-row"><span class="tf-sub">${escapeHtml(state.snapshot?.engine?.model ?? t('未选择模型'))}</span><div class="tf-actions">${state.chat.streaming ? h.button('停止生成', 'chat-abort', '', 'danger') : h.button('发送', '', '', 'primary', disabledReason)}</div></div></form></section><aside class="tf-chat-settings"><h2>${t('生成设置')}</h2>${h.kv('模型', state.snapshot?.engine?.model)}<form data-form="chat-settings">${h.textarea('System prompt','system_prompt',options.system_prompt)}${h.field('Temperature','temperature',options.temperature,{type:'number',min:0,max:5,step:0.1})}${h.field('Top P','top_p',options.top_p,{type:'number',min:0,max:1,step:0.05})}${h.field('最大 tokens','max_tokens',options.max_tokens,{type:'number',min:1,max:32768})}${h.field('Seed（留空随机）','seed',options.seed ?? '',{type:'number',min:0})}${h.select('Thinking','enable_thinking',[['true',t('启用')],['false',t('停用')]],String(options.enable_thinking))}${h.textarea('Tools JSON（可选）','tools_json',options.tools_json,{hint:'只发送 function 声明；App 不执行工具'})}${h.select('工具选择','tool_choice',[['auto','auto'],['none','none']],options.tool_choice)}<button type="submit" class="primary" ${state.chat.streaming?'disabled':''}>${t('应用生成设置')}</button></form>${h.note(disabledReason || t('停止会中断当前请求；历史、思考和工具调用保留在本机。'), Boolean(disabledReason))}</aside></div>`;
}
