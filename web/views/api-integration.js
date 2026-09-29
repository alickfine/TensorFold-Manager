import { h, html, capability } from './shared.js';
import { t } from '../i18n.js';

export function renderApi(state) {
  const settings = state.snapshot?.settings ?? {};
  const caps = state.snapshot?.capabilities ?? {};
  const keys = state.pageData.keys?.keys ?? state.snapshot?.keys ?? [];
  const gatewayState = state.snapshot?.gateway ?? {};
  const gateway = gatewayState.port ? `http://127.0.0.1:${gatewayState.port}/v1` : null;
  const gatewayStatus = !gateway ? (gatewayState.error ? t('不可用') : t('未监听')) : gatewayState.pending ? t('待重启应用') : gatewayState.error ? t('不可用') : t('已监听');
  const gatewayNotice = gatewayState.pending || gatewayState.error
    ? h.note(t('已保存端口将在 Manager 重启后绑定；当前 Base URL 仍使用实际监听端口。'), true)
    : h.note(t('网关默认仅监听 loopback。客户端密钥在本页创建。'));
  const features = [
    ['Chat Completions', capability(caps, 'chat')],
    ['Text Completions', capability(caps, 'completions')],
    ['SSE 流式输出', capability(caps, 'streaming')],
    ['Tool calling', capability(caps, 'tool_calling')],
  ];
  return h.heading('API 与集成', '集中管理端口、OpenAI 兼容端点与独立 API Key。管理令牌不会显示或复制。')
    + h.card('端点', `${h.kv('Base URL', gateway)}${h.kv('Models', gateway ? `${gateway}/models` : null)}${h.kv('Chat Completions', gateway ? `${gateway}/chat/completions` : null)}${h.kv('网关配置状态', gatewayStatus)}${h.kv('网关错误', gatewayState.error)}${gatewayNotice}`)
    + h.card('端口参数', h.form('settings-save',
      h.field('引擎端口', 'engine_port', settings.engine_port ?? '', { type:'number', min:1, max:65535 })
      + h.field('API 网关端口', 'gateway_port', settings.gateway_port ?? '', { type:'number', min:1, max:65535 }),
    '保存端口'))
    + h.card('新建推理密钥', h.form('key-create', h.field('名称', 'name', '', { required:true }) + h.field('有效天数', 'expires_days', '30', { type:'number', min:1, required:true }), '生成密钥'))
    + h.card('已签发密钥', h.table(['名称', '创建时间', '到期时间', '状态', '最近使用', '操作'], keys.map((key) => [key.name, key.created_at, key.expires_at, t(Boolean(key.enabled) ? '启用' : '停用'), key.last_used_at, html(`<div class="tf-actions">${h.button(Boolean(key.enabled) ? '停用' : '启用', 'key-toggle', key.id, 'compact')}${h.button('撤销', 'key-delete', key.id, 'compact danger')}</div>`)])))
    + h.card('运行时能力', h.table(['能力', '状态', '原因'], features.map(([name, item]) => [t(name), t(item.enabled ? '支持' : '不可用'), item.enabled ? '' : item.reason])));
}
