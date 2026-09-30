import { escapeHtml } from './views/shared.js';
import { t } from './i18n.js';

function inline(text) {
  const pattern = /`([^`]+)`|\[([^\]]+)\]\(([^)]+)\)|\*\*([^*]+)\*\*|\*([^*]+)\*/g;
  let output = '';
  let offset = 0;
  for (const match of text.matchAll(pattern)) {
    output += escapeHtml(text.slice(offset, match.index));
    if (match[1] !== undefined) output += `<code>${escapeHtml(match[1])}</code>`;
    else if (match[2] !== undefined) {
      let safe = false;
      try { safe = ['http:', 'https:'].includes(new URL(match[3]).protocol); } catch { /* malformed link */ }
      output += safe ? `<a href="${escapeHtml(match[3])}" target="_blank" rel="noopener noreferrer">${escapeHtml(match[2])}</a>` : escapeHtml(match[0]);
    } else if (match[4] !== undefined) output += `<strong>${escapeHtml(match[4])}</strong>`;
    else output += `<em>${escapeHtml(match[5])}</em>`;
    offset = match.index + match[0].length;
  }
  return output + escapeHtml(text.slice(offset));
}

export function renderChatMarkdown(value) {
  const lines = String(value ?? '').split(/\r?\n/);
  const output = [];
  let paragraph = [];
  let list = [];
  let code = null;
  let language = '';
  const flushParagraph = () => { if (paragraph.length) output.push(`<p>${paragraph.map(inline).join('<br>')}</p>`); paragraph = []; };
  const flushList = () => { if (list.length) output.push(`<ul>${list.map((item) => `<li>${inline(item)}</li>`).join('')}</ul>`); list = []; };
  const flushCode = () => {
    const lang = language.replace(/[^A-Za-z0-9+#_-]/g, '').slice(0,32);
    output.push(`<div class="tf-code-block"><div class="tf-code-toolbar"><span>${escapeHtml(lang)}</span><button type="button" data-action="chat-copy">${escapeHtml(t('复制代码'))}</button></div><pre><code>${escapeHtml(code.join('\n'))}</code></pre></div>`);
    code = null;language = '';
  };
  for (const line of lines) {
    const fence = line.match(/^\s*```(.*)$/);
    if (fence) {
      if (code) flushCode();
      else { flushParagraph();flushList();code = [];language = fence[1]; }
      continue;
    }
    if (code) { code.push(line);continue; }
    if (!line.trim()) { flushParagraph();flushList();continue; }
    const heading = line.match(/^(#{1,3})\s+(.+)$/);
    if (heading) { flushParagraph();flushList();output.push(`<h${heading[1].length + 2}>${inline(heading[2])}</h${heading[1].length + 2}>`);continue; }
    const bullet = line.match(/^\s*[-*]\s+(.+)$/);
    if (bullet) { flushParagraph();list.push(bullet[1]);continue; }
    flushList();paragraph.push(line);
  }
  if (code) flushCode();
  flushParagraph();flushList();
  return output.join('') || '';
}
