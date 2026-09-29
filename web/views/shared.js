import { t } from '../i18n.js';

export function escapeHtml(value) {
  return String(value).replace(/[&<>"']/g, (character) => ({
    '&': '&amp;',
    '<': '&lt;',
    '>': '&gt;',
    '"': '&quot;',
    "'": '&#39;',
  })[character]);
}

export function displayValue(value, suffix = '') {
  if (value === null || value === undefined) return t('未采集');
  if (typeof value === 'boolean') return value ? t('是') : t('否');
  return `${value}${suffix}`;
}

export function formatBytes(bytes) {
  if (bytes === null || bytes === undefined) return t('未采集');
  const number = Number(bytes);
  if (!Number.isFinite(number)) return escapeHtml(bytes);
  const units = ['B', 'KB', 'MB', 'GB', 'TB'];
  let value = number;
  let unit = 0;
  while (Math.abs(value) >= 1024 && unit < units.length - 1) {
    value /= 1024;
    unit += 1;
  }
  return `${value.toFixed(unit === 0 ? 0 : 1)} ${units[unit]}`;
}

export const h = {
  heading(title, description, actions = '') {
    return `<div class="tf-heading"><div><div class="tf-eyebrow">LOCAL INFERENCE WORKSPACE</div><h1>${escapeHtml(t(title))}</h1><div class="tf-sub">${escapeHtml(t(description))}</div></div><div class="tf-actions">${actions}</div></div>`;
  },
  card(title, content, action = '', translateTitle = true) {
    return `<section class="tf-card"><div class="tf-row"><h2>${escapeHtml(translateTitle ? t(title) : title)}</h2>${action}</div>${content}</section>`;
  },
  metric(label, value, note = '') {
    return `<div class="tf-metric"><div class="tf-metric-label">${escapeHtml(t(label))}</div><div class="tf-value">${escapeHtml(displayValue(value))}</div><div class="tf-metric-note">${escapeHtml(t(note))}</div></div>`;
  },
  kv(label, value) {
    return `<div class="tf-kv"><span>${escapeHtml(t(label))}</span><span>${escapeHtml(displayValue(value))}</span></div>`;
  },
  note(text, warning = false) {
    return `<div class="tf-note${warning ? ' warn' : ''}">${escapeHtml(text)}</div>`;
  },
  tag(text, tone = '') {
    return `<span class="tf-tag ${escapeHtml(tone)}">${escapeHtml(displayValue(text))}</span>`;
  },
  button(text, action, value = '', tone = '', disabledReason = '') {
    const disabled = disabledReason ? ' disabled' : '';
    const title = disabledReason ? ` title="${escapeHtml(disabledReason)}"` : '';
    return `<button class="${escapeHtml(tone)}" data-action="${escapeHtml(action)}" data-value="${escapeHtml(value)}"${disabled}${title}>${escapeHtml(t(text))}</button>`;
  },
  table(columns, rows, empty = '暂无数据') {
    if (!rows?.length) return `<div class="tf-empty">${escapeHtml(t(empty))}</div>`;
    return `<div class="tf-table-wrap"><table class="tf-table"><thead><tr>${columns.map((item) => `<th>${escapeHtml(t(item))}</th>`).join('')}</tr></thead><tbody>${rows.map((row) => `<tr>${row.map((cell) => `<td>${cell?.html === true ? cell.value : escapeHtml(displayValue(cell))}</td>`).join('')}</tr>`).join('')}</tbody></table></div>`;
  },
  field(label, name, value = '', { type = 'text', hint = '', disabled = false, required = false, full = false, min, max, step } = {}) {
    const limits = `${min !== undefined ? ` min="${escapeHtml(min)}"` : ''}${max !== undefined ? ` max="${escapeHtml(max)}"` : ''}${step !== undefined ? ` step="${escapeHtml(step)}"` : ''}`;
    return `<div class="tf-field${full ? ' full' : ''}"><label for="field-${escapeHtml(name)}">${escapeHtml(t(label))}</label><input id="field-${escapeHtml(name)}" name="${escapeHtml(name)}" type="${escapeHtml(type)}" value="${escapeHtml(value ?? '')}"${disabled ? ' disabled' : ''}${required ? ' required' : ''}${limits}>${hint ? `<div class="tf-sub">${escapeHtml(t(hint))}</div>` : ''}</div>`;
  },
  textarea(label, name, value = '', { hint = '', required = false, full = true, placeholder = '' } = {}) {
    return `<div class="tf-field${full ? ' full' : ''}"><label for="field-${escapeHtml(name)}">${escapeHtml(t(label))}</label><textarea id="field-${escapeHtml(name)}" name="${escapeHtml(name)}"${required ? ' required' : ''} placeholder="${escapeHtml(t(placeholder))}">${escapeHtml(value ?? '')}</textarea>${hint ? `<div class="tf-sub">${escapeHtml(t(hint))}</div>` : ''}</div>`;
  },
  select(label, name, options, selected = '', { hint = '', full = false } = {}) {
    return `<div class="tf-field${full ? ' full' : ''}"><label for="field-${escapeHtml(name)}">${escapeHtml(t(label))}</label><select id="field-${escapeHtml(name)}" name="${escapeHtml(name)}">${options.map(([value, text]) => `<option value="${escapeHtml(value)}"${String(value) === String(selected ?? '') ? ' selected' : ''}>${escapeHtml(text)}</option>`).join('')}</select>${hint ? `<div class="tf-sub">${escapeHtml(t(hint))}</div>` : ''}</div>`;
  },
  checkbox(label, name, checked = false, { hint = '', disabled = false } = {}) {
    return `<div class="tf-field full"><label class="tf-check"><input name="${escapeHtml(name)}" type="checkbox"${checked ? ' checked' : ''}${disabled ? ' disabled' : ''}> ${escapeHtml(t(label))}</label>${hint ? `<div class="tf-sub">${escapeHtml(t(hint))}</div>` : ''}</div>`;
  },
  form(action, fields, submit = '保存', extra = '') {
    return `<form data-form="${escapeHtml(action)}"><div class="tf-form-grid">${fields}</div><div class="tf-actions form-actions">${extra}<button type="submit" class="primary">${escapeHtml(t(submit))}</button></div></form>`;
  },
};

export function html(value) {
  return { html: true, value };
}

export function capability(capabilities, name) {
  const raw = capabilities?.[name];
  if (raw === true) return { enabled: true, reason: '' };
  if (raw && typeof raw === 'object') {
    const reported = Boolean(raw.enabled ?? raw.available ?? raw.supported);
    const ready = raw.ready !== false && raw.available !== false;
    return { enabled: reported && ready, reason: raw.reason ?? raw.message ?? (ready ? '' : t('能力尚未准备完成')) };
  }
  return { enabled: false, reason: typeof raw === 'string' ? raw : t('当前运行时未报告支持') };
}

export function formValues(form) {
  return Object.fromEntries(new FormData(form).entries());
}
