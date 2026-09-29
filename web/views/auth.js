import { h, html } from './shared.js';
import { t } from '../i18n.js';

export function renderAuth(state) {
  const keys = state.pageData.keys?.keys ?? state.snapshot?.keys ?? [];
  return h.heading('认证与密钥', '推理 API Key 仅在创建时展示一次；服务端只持久化哈希。')
    + h.card('新建推理密钥', h.form('key-create', h.field('名称', 'name', '', { required:true }) + h.field('有效天数', 'expires_days', '30', { type:'number', min:1, required:true }), '生成密钥'))
    + h.card('已签发密钥', h.table(['名称', '创建时间', '到期时间', '状态', '最近使用', '操作'], keys.map((key) => [key.name, key.created_at, key.expires_at, t(Boolean(key.enabled) ? '启用' : '停用'), key.last_used_at, html(`<div class="tf-actions">${h.button(Boolean(key.enabled) ? '停用' : '启用', 'key-toggle', key.id, 'compact')}${h.button('撤销', 'key-delete', key.id, 'compact danger')}</div>`)])));
}
