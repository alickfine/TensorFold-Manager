import { EN_MESSAGES } from './i18n-catalog.js';

export const SUPPORTED_LOCALES = Object.freeze(['zh-CN', 'en']);
export const LOCALE_STORAGE_KEY = 'tensorfold.locale';

let currentLocale = 'zh-CN';

function safeGet(storage, key) {
  try { return storage?.getItem?.(key) ?? null; } catch { return null; }
}

function safeSet(storage, key, value) {
  try { storage?.setItem?.(key, value); } catch { /* private browsing or disabled storage */ }
}

export function isSupportedLocale(value) {
  return SUPPORTED_LOCALES.includes(value);
}

export function resolveInitialLocale({ storage = globalThis.localStorage, navigator = globalThis.navigator } = {}) {
  const stored = safeGet(storage, LOCALE_STORAGE_KEY);
  if (isSupportedLocale(stored)) return stored;
  return String(navigator?.language ?? '').toLowerCase().startsWith('zh') ? 'zh-CN' : 'en';
}

export function getLocale() {
  return currentLocale;
}

export function setLocale(locale, {
  storage = globalThis.localStorage,
  document = globalThis.document,
  webkit = globalThis.window?.webkit,
} = {}) {
  if (!isSupportedLocale(locale)) return false;
  currentLocale = locale;
  if (document?.documentElement) document.documentElement.lang = locale;
  safeSet(storage, LOCALE_STORAGE_KEY, locale);
  const handler = webkit?.messageHandlers?.language;
  if (typeof handler?.postMessage === 'function') {
    try {
      const reply = handler.postMessage(locale);
      if (reply && typeof reply.catch === 'function') reply.catch(() => {});
    } catch { /* native bridge is best-effort until the instance is ready */ }
  }
  return locale;
}

export function initializeLocale(options = {}) {
  const locale = resolveInitialLocale(options);
  return setLocale(locale, options);
}

export function t(source, replacements = {}) {
  const template = currentLocale === 'en' ? (EN_MESSAGES[source] ?? source) : source;
  return template.replace(/\{([a-zA-Z0-9_]+)\}/g, (match, key) => (
    Object.hasOwn(replacements, key) ? String(replacements[key]) : match
  ));
}

export function translateDocument(root = globalThis.document) {
  root?.querySelectorAll?.('[data-i18n]').forEach((element) => {
    element.textContent = t(element.dataset.i18n);
  });
  root?.querySelectorAll?.('[data-i18n-aria-label]').forEach((element) => {
    element.setAttribute('aria-label', t(element.dataset.i18nAriaLabel));
  });
  const selector = root?.querySelector?.('#language-select');
  if (selector) selector.value = currentLocale;
}
