import { h, escapeHtml, capability, formatNumber } from './shared.js';
import { parseChatOptions } from '../chat-options.js';
import { renderChatMarkdown } from '../chat-markdown.js';
import { t } from '../i18n.js';

function messages(items, streaming = false) {
  if (!items?.length) return `<div class="tf-chat-welcome"><strong>${escapeHtml(t('开始一段真实本机对话'))}</strong><p>${escapeHtml(t('对话保存在本机；工具调用仅展示，不会由 App 执行。'))}</p></div>`;
  return items.map((message, index) => {
    const assistant = message.role === 'assistant';
    const content = renderChatMarkdown(message.content ?? '');
    const status = message.status && message.status !== 'completed' ? h.tag(t(message.status), message.status === 'failed' ? 'red' : 'amber') : '';
    const metrics = message.metrics ? `<div class="tf-chat-metrics">${t('浏览器耗时')} ${escapeHtml(formatNumber(message.metrics.elapsed_seconds ?? 0))}s · ${escapeHtml(formatNumber(message.metrics.completion_tokens ?? t('未采集')))} tokens · ${escapeHtml(formatNumber(message.metrics.tokens_per_second ?? t('未采集')))} tok/s</div>` : '';
    const reasoning = message.reasoning ? `<details class="tf-chat-detail"><summary>${escapeHtml(t('思考过程'))}</summary><pre>${escapeHtml(message.reasoning)}</pre></details>` : '';
    const tools = message.tool_calls?.length ? `<details class="tf-chat-detail"><summary>${escapeHtml(t('工具调用（仅展示，未执行）'))}</summary><pre>${escapeHtml(JSON.stringify(message.tool_calls,null,2))}</pre></details>` : '';
    const error = message.error ? `<div class="tf-note warn">${escapeHtml(message.error)}</div>` : '';
    const retry = assistant && index === items.length - 1 && ['failed','cancelled'].includes(message.status) && !streaming;
    return `<article class="tf-message ${assistant ? 'assistant' : 'user'}"><div class="tf-avatar">${assistant ? 'TF' : escapeHtml(t('你'))}</div><div class="tf-message-content"><div class="tf-message-head"><strong>${assistant ? 'TensorFold' : escapeHtml(t('你'))}</strong>${status}</div><div class="tf-message-body">${content}</div>${error}${reasoning}${tools}${metrics}<div class="tf-message-actions">${h.button('复制', 'chat-copy')}${retry ? h.button('重试', 'chat-retry') : ''}</div></div></article>`;
  }).join('');
}

export function renderChat(state) {
  const chat = state.chat ?? {};
  const settings = state.snapshot?.settings ?? {};
  const options = parseChatOptions(chat.options ?? {},settings);
  const ready = ['ready', 'attached'].includes(state.snapshot?.engine?.state);
  const chatGate = capability(state.snapshot?.capabilities, 'chat');
  const streamGate = capability(state.snapshot?.capabilities, 'streaming');
  const disabledReason = !ready ? t('引擎尚未就绪') : !chatGate.enabled ? chatGate.reason : !streamGate.enabled ? streamGate.reason : '';
  const model = ready ? state.snapshot?.engine?.model ?? '' : '';
  const drawerMode = chat.settingsOpen === null || chat.settingsOpen === undefined ? 'auto' : chat.settingsOpen ? 'open' : 'closed';
  const sessions = chat.sessions ?? [];
  const current = sessions.find((item) => item.id === chat.activeId);
  return h.heading('内置聊天', '通过当前 TensorFold 服务进行真实流式对话。')
    + `<div class="tf-chat-layout ${drawerMode}" aria-label="${escapeHtml(t('聊天工作区'))}"><div class="tf-chat-sidebar" role="region" aria-label="${escapeHtml(t('对话列表'))}"><div class="tf-chat-sidebar-head">${h.button('新对话', 'chat-new', '', 'primary')}</div><label class="sr-only" for="chat-search">${escapeHtml(t('搜索对话'))}</label><input id="chat-search" type="search" placeholder="${escapeHtml(t('搜索对话'))}"><div class="tf-chat-sessions">${sessions.map((session) => `<button class="tf-chat-session${session.id === chat.activeId ? ' active' : ''}" data-action="chat-open" data-value="${escapeHtml(session.id)}" title="${escapeHtml(session.title)}">${escapeHtml(session.title)}</button>`).join('') || `<div class="tf-empty">${escapeHtml(t('暂无对话'))}</div>`}</div></div>`
    + `<section class="tf-chat-main" role="region" aria-label="${escapeHtml(t('消息'))}"><div class="tf-chat-toolbar"><div class="tf-chat-current"><strong>${escapeHtml(current?.title ?? t('新对话'))}</strong><span>${escapeHtml(model || t('未选择模型'))}</span></div><div class="tf-actions">${current ? h.button('重命名', 'chat-rename') : ''}${h.button('切换模型', 'goto', 'models')}${h.button('导出 JSON', 'chat-export')}${h.button('生成设置', 'chat-settings-toggle', '', 'compact')}</div></div>`
    + `<div id="chat-messages" class="tf-messages">${messages(chat.messages, chat.streaming)}</div><form class="tf-composer" data-form="chat-send"><label class="sr-only" for="chat-input">${escapeHtml(t('消息'))}</label><textarea id="chat-input" name="message" placeholder="${escapeHtml(t('输入消息'))}" required></textarea><div class="tf-row"><span class="tf-sub">${escapeHtml(disabledReason || t('Enter 发送 · Shift+Enter 换行'))}</span><div class="tf-actions">${chat.streaming ? h.button('停止', 'chat-abort', '', 'danger') : h.button('生成', '', '', 'primary', disabledReason)}</div></div></form></section>`
    + `<aside class="tf-chat-settings" role="region" aria-label="${escapeHtml(t('生成设置'))}"><div class="tf-row"><h2>${escapeHtml(t('生成设置'))}</h2>${h.button('关闭生成设置', 'chat-settings-close', '', 'compact')}</div>`
    + `<div class="tf-chat-parameters"><form data-form="chat-settings"><div class="tf-form-grid">${h.textarea('System prompt','system_prompt',options.system_prompt)}${h.field('Temperature','temperature',options.temperature,{type:'number',min:0,max:5,step:0.1})}${h.field('Top P','top_p',options.top_p,{type:'number',min:0,max:1,step:0.05})}${h.field('最大 tokens','max_tokens',options.max_tokens,{type:'number',min:1,max:32768})}${h.field('Seed（留空随机）','seed',options.seed ?? '',{type:'number',min:0})}${h.select('Thinking','enable_thinking',[['true',t('启用')],['false',t('停用')]],String(options.enable_thinking))}${h.textarea('Tools JSON（可选）','tools_json',options.tools_json,{hint:'只发送 function 声明；App 不执行工具'})}${h.select('工具选择','tool_choice',[['auto','auto'],['none','none']],options.tool_choice)}</div><div class="tf-actions form-actions"><button type="submit" class="primary" ${chat.streaming?'disabled':''}>${escapeHtml(t('应用生成设置'))}</button></div></form></div>`
    + `</aside></div>`;
}
