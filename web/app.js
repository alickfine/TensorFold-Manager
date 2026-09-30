import { api, getAdminToken, getBootstrapLanguage } from './api.js';
import { exportTextFile } from './export.js';
import { parseChatOptions, prepareChatTurn, prepareRetryTurn, chatRequest, isUntitledConversation, conversationTitleFromMessage, applySavedConversation } from './chat-options.js';
import { renderChatMarkdown } from './chat-markdown.js';
import { serviceSwitchRequest, engineStopRequest, engineDetachRequest, catalogDownloadRequest, shouldPollLivePage, isPollEditingTarget, isChatSubmitKey } from './contracts.js';
import { withChatSubmitLock } from './chat-submit.js';
import { formValues, escapeHtml, capability } from './views/shared.js';
import { serializeSettings, partitionProfileConfig } from './views/settings.js';
import { renderOverview } from './views/overview.js';
import { renderResourceReport } from './views/resources.js';
import { renderStats } from './views/stats.js';
import { renderCache } from './views/cache.js';
import { renderModelWorkspace } from './views/model-workspace.js';
import { renderModelConfigDialog } from './views/model-config.js';
import { renderEngineConfig } from './views/engine-config.js';
import { renderServer } from './views/server.js';
import { renderApi } from './views/api-integration.js';
import { renderUpdates } from './views/updates.js';
import { renderLogs } from './views/logs.js';
import { renderBenchmark, benchmarkRequest } from './views/benchmark.js';
import { renderChat } from './views/chat.js';
import { renderActivity } from './views/activity.js';
import { renderWorkspaceSettings } from './views/workspace-settings.js';
import { getLocale, initializeLocale, setLocale, t, translateDocument } from './i18n.js';
import { captureFormDraft, restoreFormDraft } from './form-draft.js';
import { dispatchDocumentClick } from './click-routing.js';
import { resolveWorkspaceRoute } from './workspace-route.js';

const renderers = {
  overview:renderOverview, models:renderModelWorkspace, chat:renderChat,
  activity:renderActivity, settings:renderWorkspaceSettings,
};

const state = {
  page:'overview', routeQuery:new URLSearchParams(), snapshot:null, pageData:{}, loading:true,
  filters:{ statsModel:'', statsRange:'24h', logLevel:'', logQuery:'', logLimit:'500' }, launchTarget:'', modelSearch:'',
  chat:{ sessions:[], activeId:null, revision:null, messages:[], options:{}, streaming:false, controller:null, pendingSaves:new Map(), openSequence:0, settingsOpen:null }, modelConfigTarget:'',
};

const pageElement = document.querySelector('#page');
const toastElement = document.querySelector('#toast');
let toastTimer;
let pageDirty = false;

initializeLocale({ webkit:null });
translateDocument();

function toast(message, error = false) {
  toastElement.textContent = message;
  toastElement.classList.toggle('error-panel', error);
  toastElement.hidden = false;
  clearTimeout(toastTimer);
  toastTimer = setTimeout(() => { toastElement.hidden = true; }, 4000);
}

function showModal(title, body) {
  document.querySelector('#modal').dataset.title = title;
  document.querySelector('#modal-title').textContent = t(title);
  document.querySelector('#modal-body').innerHTML = body;
  document.querySelector('#modal').hidden = false;
}

function closeModal() {
  document.querySelector('#modal').hidden = true;
  delete document.querySelector('#modal').dataset.title;
  document.querySelector('#modal-body').replaceChildren();
  state.modelConfigTarget = '';
}

function refreshModelConfigModal({ preserveDraft = false } = {}) {
  const modal = document.querySelector('#modal');
  if (modal.hidden || modal.dataset.title !== '模型配置' || !state.modelConfigTarget) return;
  const body = document.querySelector('#modal-body');
  const draft = preserveDraft ? captureFormDraft(body) : [];
  document.querySelector('#modal-title').textContent = t('模型配置');
  body.innerHTML = renderModelConfigDialog(state, state.modelConfigTarget);
  if (preserveDraft) restoreFormDraft(body, draft);
}

function routeFromHash() {
  pageDirty = false;
  const route = resolveWorkspaceRoute(location.hash);
  state.page = route.page;
  state.routeQuery = route.query;
}

function navigate(target) {
  const route = resolveWorkspaceRoute(`#${target}`);
  const [candidate] = String(target).split('?');
  if (route.page === 'overview' && candidate !== 'overview' && candidate !== 'stats') return;
  location.hash = `${route.page}${route.query.size ? `?${route.query}` : ''}`;
}

function updateChrome() {
  const engine = state.snapshot?.engine ?? {};
  document.querySelector('#app-version').textContent = `App ${state.snapshot?.app_version ?? t('版本未采集')}`;
  document.querySelector('#side-status').textContent = engine.state ?? t('未连接');
  const led = document.querySelector('#side-led');
  led.className = `tf-led ${engine.state === 'ready' || engine.state === 'attached' ? '' : engine.state === 'failed' ? 'red' : 'amber'}`;
  document.querySelectorAll('button[data-page]').forEach((button) => {
    const active = button.dataset.page === state.page;
    button.classList.toggle('active', active);
    if (active) button.setAttribute('aria-current', 'page'); else button.removeAttribute('aria-current');
  });
}

function updateLanguageButton() {
  const button = document.querySelector('#language-toggle');
  const label = getLocale() === 'zh-CN' ? 'Switch to English' : '切换为中文';
  button.setAttribute('aria-label', label);
  button.title = label;
}

function renderCurrent() {
  updateChrome();
  const renderer = renderers[state.page];
  pageElement.dataset.view = state.page;
  pageElement.innerHTML = renderer(state);
  pageElement.focus({ preventScroll:true });
}

function renderCurrentPreservingDraft(submittedMessage = null) {
  const draft = captureFormDraft(pageElement);
  if (submittedMessage !== null) {
    const composer = draft.find((item) => item.name === 'message');
    if (composer && composer.value.trim() === submittedMessage) {
      composer.value = '';
      composer.selectionStart = 0;
      composer.selectionEnd = 0;
    }
  }
  const messages = pageElement.querySelector('#chat-messages');
  const scrollTop = messages?.scrollTop;
  const follow = messages && messages.scrollHeight - messages.scrollTop - messages.clientHeight < 120;
  renderCurrent();
  restoreFormDraft(pageElement, draft);
  const next = pageElement.querySelector('#chat-messages');
  if (next && scrollTop !== undefined) next.scrollTop = follow ? next.scrollHeight : scrollTop;
}

function applyLanguage(locale) {
  const draft = captureFormDraft(pageElement);
  const messageScroll = pageElement.querySelector('#chat-messages')?.scrollTop;
  const modalBody = document.querySelector('#modal-body');
  const modalDraft = captureFormDraft(modalBody);
  if (!setLocale(locale)) return false;
  translateDocument();
  updateLanguageButton();
  if (state.snapshot) {
    renderCurrent();
    restoreFormDraft(pageElement, draft);
    if (messageScroll !== undefined) pageElement.querySelector('#chat-messages').scrollTop = messageScroll;
    refreshModelConfigModal();
    restoreFormDraft(modalBody, modalDraft);
  }
  return true;
}

window.TensorFoldLanguage = Object.freeze({
  getLocale,
  setLocale:applyLanguage,
});

function renderFatal(error) {
  pageElement.innerHTML = `<section class="tf-card error-panel"><h1>${t('无法连接管理服务')}</h1><p>${escapeHtml(error.message)}</p><p class="tf-sub">${t('请从 TensorFold Manager App 启动页面。浏览器开发测试需要显式 loopback dev 模式。')}</p></section>`;
  document.querySelector('#side-status').textContent = t('连接失败');
  document.querySelector('#side-led').className = 'tf-led red';
}

async function refreshSnapshot({ render = true } = {}) {
  state.snapshot = await api.request('/api/state');
  if (render) renderCurrent(); else updateChrome();
}

async function loadPageData(page = state.page, { render = true } = {}) {
  if (page === 'overview') {
    state.pageData.services = await api.request('/api/services');
    const params = new URLSearchParams({ range:state.filters.statsRange });
    if (state.filters.statsModel) params.set('model', state.filters.statsModel);
    state.pageData.stats = await api.request(`/api/stats?${params}`);
  } else if (page === 'models' && state.routeQuery.get('section') === 'downloads') {
    const [catalog, jobs] = await Promise.all([api.request('/api/downloads/catalog'), api.request('/api/jobs')]);
    state.pageData.catalog = catalog;
    state.pageData.jobs = jobs;
  } else if (page === 'models') {
    state.pageData.profiles = await api.request('/api/profiles');
  } else if (page === 'settings') {
    const section = state.routeQuery.get('section');
    if (section === 'storage') state.pageData.cache = await api.request('/api/cache');
    if (section === 'api') state.pageData.keys = await api.request('/api/keys');
    if (section === 'updates') state.pageData.updates = await api.request('/api/updates');
  } else if (page === 'activity') {
    if (state.routeQuery.get('section') === 'benchmark') state.pageData.benchmark = await api.request('/api/benchmark/results');
    else {
    const params = new URLSearchParams({ level:state.filters.logLevel, query:state.filters.logQuery, limit:state.filters.logLimit });
    state.pageData.logs = await api.request(`/api/logs?${params}`);
    }
  } else if (page === 'chat') {
    if (!state.chat.streaming) {
      const { sessions } = await api.request('/api/chat/sessions');
      state.chat.sessions = sessions ?? [];
      if (!sessions.some((item) => item.id === state.chat.activeId)) state.chat.activeId = sessions[0]?.id ?? null;
      if (state.chat.activeId) await openChatSession(state.chat.activeId, { render:false });
      else { state.chat.messages = [];state.chat.revision = null; }
    }
  }
  if (render) renderCurrent();
}

async function openChatSession(id, { render = true } = {}) {
  if (state.chat.streaming || state.chat.submitting) throw new Error(t('请先停止当前生成'));
  const sequence = ++state.chat.openSequence;
  if (state.chat.pendingSaves.has(id)) await state.chat.pendingSaves.get(id);
  if (sequence !== state.chat.openSequence) return;
  const session = await api.request(`/api/chat/sessions/${encodeURIComponent(id)}`);
  if (sequence !== state.chat.openSequence) return;
  state.chat.activeId = session.id;
  state.chat.revision = session.revision;
  state.chat.messages = session.messages ?? [];
  state.chat.options = state.chat.messages.findLast((message) => message.options)?.options ?? state.chat.options;
  if (render) renderCurrent();
}

async function refreshAll() {
  await refreshSnapshot({ render:false });
  await loadPageData(state.page, { render:false });
  renderCurrent();
}

async function run(label, operation, { refresh = true } = {}) {
  try {
    const result = await operation();
    pageDirty = false;
    if (refresh) await refreshAll();
    toast(t(label));
    return result;
  } catch (error) {
    toast(error.message ?? String(error), true);
    if (error && typeof error === 'object') error.reported = true;
    if (error.details?.resources) showModal('内存与服务检查未通过', renderResourceReport(error.details.resources));
    throw error;
  }
}

async function engineAction(action, explicitModel = '') {
  const selected = explicitModel || state.launchTarget || document.querySelector('[data-role="engine-model"]')?.value || state.snapshot?.settings?.selected_model;
  if ((action === 'start' || action === 'restart') && !selected) throw new Error(t('请先选择模型'));
  const path = `/api/engine/${action}`;
  const body = action === 'stop' ? engineStopRequest(false).options.body : { model:selected };
  await run(action === 'stop' ? '已提交停止请求' : action === 'restart' ? '已提交重启请求' : '已提交启动请求', () => api.request(path, { method:'POST', body }));
}

async function saveText(path, filename) {
  const blob = await api.download(path);
  return exportTextFile({ name:filename, content:await blob.text() });
}

async function handleAction(action, value, element) {
  if (action === 'logs-export') {
    const records = state.pageData.logs?.logs ?? [];
    const result = await exportTextFile({name:'tensorfold-logs.json',content:JSON.stringify(records,null,2)});
    if (result.saved) toast(t('脱敏日志已导出'));
    return;
  }
  if (action === 'refresh') return refreshAll();
  if (action === 'goto') return navigate(value);
  if (action === 'section') { const [page, section] = value.split(':'); return navigate(`${page}?section=${section}`); }
  if (action === 'load-page') return loadPageData(value || state.page);
  if (action === 'modal-close') return closeModal();
  if (action === 'engine-start') return engineAction('start', value);
  if (action === 'engine-stop') {
    if (confirm(t('停止 TensorFold 推理服务？在途请求将按后端排空策略处理。'))) return engineAction('stop');
    return;
  }
  if (action === 'engine-force-stop') {
    if (!confirm(t('仅强制停止 TensorFold Manager 当前持有的自有引擎进程？此操作不会按 PID 或端口定位其他服务。'))) return;
    const request = engineStopRequest(true);
    return run('自有服务强制停止请求已提交', () => api.request(request.path, request.options));
  }
  if (action === 'engine-detach') {
    const request = engineDetachRequest();
    return run('已断开只读外部服务连接；外部进程继续运行', () => api.request(request.path, request.options));
  }
  if (action === 'engine-restart') return engineAction('restart', value);
  if (action === 'model-default') return run('默认模型已保存', () => api.request('/api/settings', { method:'PUT', body:{ selected_model:value } }));
  if (action === 'models-scan') return run('模型扫描完成', () => api.request('/api/models/scan', { method:'POST', body:{} }));
  if (action === 'models-discover') return run('全盘模型扫描任务已创建', () => api.request('/api/models/discover', { method:'POST', body:{} }));
  if (action === 'model-validate') return run('兼容性预检通过；这是 CLI 兼容性证据，尚未加载模型', () => api.request('/api/models/validate', { method:'POST', body:{ model:value } }));
  if (action === 'model-config-open') {
    state.modelConfigTarget = value;
    if (!state.pageData.profiles) state.pageData.profiles = await api.request('/api/profiles');
    return showModal('模型配置', renderModelConfigDialog(state, value));
  }
  if (action === 'model-select') return navigate(`models?model=${encodeURIComponent(value)}`);
  if (action === 'job-action') {
    const separator = value.lastIndexOf(':');
    const id = value.slice(0, separator);
    const verb = value.slice(separator + 1);
    if (verb === 'cancel' && !confirm(t('取消任务并保留可续传文件？'))) return;
    return run(t('任务操作已提交：{verb}', { verb }), () => api.request(`/api/jobs/${encodeURIComponent(id)}/${verb}`, { method:'POST', body:{} }));
  }
  if (action === 'profile-delete') {
    if (confirm(t('删除这个配置档？'))) {
      const result = await run('配置档已删除', () => api.request(`/api/profiles/${encodeURIComponent(value)}`, { method:'DELETE' }));
      refreshModelConfigModal();
      return result;
    }
    return;
  }
  if (action === 'profile-export') {
    const profiles = state.pageData.profiles?.profiles ?? state.snapshot?.profiles ?? [];
    const profile = profiles.find((item) => item.id === value);
    if (!profile) throw new Error(t('配置档不存在'));
    const result = await exportTextFile({ name:`profile-${profile.id}.json`, content:JSON.stringify({ schema:1, profile }, null, 2) });
    if (result.saved) toast(t('配置档已导出'));
    return;
  }
  if (action === 'profile-apply') {
    const profiles = state.pageData.profiles?.profiles ?? state.snapshot?.profiles ?? [];
    const profile = profiles.find((item) => item.id === value);
    if (!profile) throw new Error(t('配置档不存在'));
    const requested = state.modelConfigTarget || state.routeQuery.get('model');
    const models = state.snapshot?.models ?? [];
    const target = models.find((model) => model.id === requested)?.id ?? models.find((model) => model.id === state.snapshot?.settings?.selected_model || model.repo === state.snapshot?.settings?.selected_model)?.id;
    if (!target) throw new Error(t('请先明确选择配置档的应用目标模型'));
    const { settings, modelConfig } = partitionProfileConfig(profile.config ?? {});
    if (profile.config?.selected_model && profile.config.selected_model !== target && !confirm(t('配置档记录的默认模型为：\n{profileModel}\n\n本次明确应用到当前模型：\n{target}\n\n继续吗？', { profileModel:profile.config.selected_model, target }))) return;
    const result = await run('配置档已应用；运行中参数等待重启生效', async () => {
      if (Object.keys(modelConfig).length) await api.request('/api/models/config', { method:'PUT', body:{ model:target, config:modelConfig } });
      await api.request('/api/settings', { method:'PUT', body:{ ...settings, selected_model:target } });
      return {};
    });
    closeModal();
    return result;
  }
  if (action === 'cache-clear') {
    if (confirm(t('清理后端确认归属的受管快照？'))) return run('缓存清理完成', () => api.request('/api/cache/clear', { method:'POST', body:{ confirm:true } }));
    return;
  }
  if (action === 'stats-export') {
    const params = new URLSearchParams({ range:state.filters.statsRange });
    if (state.filters.statsModel) params.set('model', state.filters.statsModel);
    try {
      const result = await saveText(`/api/stats/export?${params}`, 'tensorfold-stats.csv');
      if (result.saved) toast(t('CSV 已保存'));
    } catch (error) {
      toast(error.message ?? String(error), true);
    }
    return;
  }
  if (action === 'key-toggle') return run('密钥状态已更新', () => api.request(`/api/keys/${encodeURIComponent(value)}/toggle`, { method:'POST', body:{} }));
  if (action === 'key-delete') {
    if (confirm(t('撤销这个 API Key？现有客户端将立即无法继续使用。'))) return run('密钥已撤销', () => api.request(`/api/keys/${encodeURIComponent(value)}`, { method:'DELETE' }));
    return;
  }
  if (action === 'update-check') return run('更新检查完成', () => api.request('/api/updates/check', { method:'POST', body:{} }));
  if (action === 'update-upgrade') {
    const body = {};
    if (value) body.version = value;
    const model = state.snapshot?.engine?.model ?? state.snapshot?.settings?.selected_model;
    if (model) body.model = model;
    return run('引擎升级任务已创建', () => api.request('/api/updates/upgrade', { method:'POST', body }));
  }
  if (action === 'update-install') return run('候选安装任务已创建', () => api.request('/api/updates/install', { method:'POST', body:{ version:value } }));
  if (action === 'update-activate') {
    if (confirm(t('排空请求并激活已验证的候选版本？'))) return run('候选激活流程已提交', () => api.request('/api/updates/activate', { method:'POST', body:{} }));
    return;
  }
  if (action === 'update-rollback') {
    if (confirm(t('回退到上一个已验证版本？'))) return run('回退流程已提交', () => api.request('/api/updates/rollback', { method:'POST', body:{} }));
    return;
  }
  if (action === 'engine-install') return run('官方引擎安装任务已创建', () => api.request('/api/engine/install', { method:'POST', body:{} }));
  if (action === 'logs-filter') return loadPageData('activity');
  if (action === 'chat-settings-toggle' || action === 'chat-settings-close') {
    const draft = captureFormDraft(pageElement);
    state.chat.settingsOpen = action === 'chat-settings-close' ? false : !(state.chat.settingsOpen ?? window.matchMedia('(min-width:1101px)').matches);
    renderCurrent();
    restoreFormDraft(pageElement, draft);
    return;
  }
  if (action === 'chat-abort') {
    state.chat.controller?.abort();
    return;
  }
  if (action === 'chat-export') {
    const result = await exportTextFile({name:'tensorfold-chat.json',content:JSON.stringify({schema:2,session_id:state.chat.activeId,messages:state.chat.messages},null,2)});
    if (result.saved) toast(t('对话已导出'));
    return;
  }
  if (action === 'chat-new') {
    if (state.chat.streaming || state.chat.submitting) throw new Error(t('请先停止当前生成'));
    const session = await api.request('/api/chat/sessions', { method:'POST', body:{ title:t('新对话') } });
    state.chat.sessions = [session, ...state.chat.sessions];
    state.chat.activeId = session.id;
    state.chat.revision = session.revision;
    state.chat.messages = [];
    renderCurrent();
    return;
  }
  if (action === 'chat-open') return openChatSession(value);
  if (action === 'chat-rename') {
    const current = state.chat.sessions.find((item) => item.id === state.chat.activeId);
    if (current) showModal('重命名对话', `<form data-form="chat-rename"><label for="chat-title">${t('名称')}</label><input id="chat-title" name="title" maxlength="120" required value="${escapeHtml(current.title)}"><div class="tf-actions form-actions"><button type="submit" class="primary">${t('保存')}</button></div></form>`);
    return;
  }
  if (action === 'chat-copy') {
    const text = element.closest('.tf-code-block')?.querySelector('code')?.textContent ?? element.closest('.tf-message')?.querySelector('.tf-message-body')?.textContent ?? '';
    try { await navigator.clipboard.writeText(text); }
    catch {
      const temp = document.createElement('textarea');temp.value = text;document.body.append(temp);temp.select();document.execCommand('copy');temp.remove();
    }
    toast(t('已复制'));
    return;
  }
  if (action === 'chat-retry') return sendChat('', { retry:true });
}

async function persistChat() {
  const id = state.chat.activeId;
  if (!id) return;
  const current = state.chat.sessions.find((item) => item.id === id);
  const title = isUntitledConversation(current?.title) ? conversationTitleFromMessage(state.chat.messages.find((item) => item.role === 'user')?.content, t('新对话')) : undefined;
  const body = { revision:state.chat.revision, messages:state.chat.messages };
  if (title) body.title = title;
  const pending = api.request(`/api/chat/sessions/${encodeURIComponent(id)}`, { method:'PUT', body });
  state.chat.pendingSaves.set(id, pending);
  try {
    const session = await pending;
    applySavedConversation(state.chat, session);
  } finally {
    if (state.chat.pendingSaves.get(id) === pending) state.chat.pendingSaves.delete(id);
  }
}

async function sendChat(message, { retry = false } = {}) {
  let acquired = false;
  try {
    return await withChatSubmitLock(state.chat, () => {
      acquired = true;
      return performChatSend(message, { retry });
    });
  } finally {
    if (acquired && state.page === 'chat') renderCurrentPreservingDraft();
  }
}

async function performChatSend(message, { retry = false } = {}) {
  const submitButton = pageElement.querySelector('.tf-composer button[data-action=""]');
  if (submitButton) submitButton.disabled = true;
  const originalSessionId = state.chat.activeId;
  if (originalSessionId && state.chat.pendingSaves.has(originalSessionId)) await state.chat.pendingSaves.get(originalSessionId);
  if (state.chat.activeId !== originalSessionId) throw new Error(t('对话已切换，请重新发送'));
  const streamCapability = capability(state.snapshot?.capabilities, 'streaming');
  const chatCapability = capability(state.snapshot?.capabilities, 'chat');
  if (!streamCapability.enabled || !chatCapability.enabled) throw new Error(!chatCapability.enabled ? chatCapability.reason : streamCapability.reason);
  if (!retry && !state.chat.activeId) {
    const session = await api.request('/api/chat/sessions', { method:'POST', body:{ title:conversationTitleFromMessage(message, t('新对话')) } });
    state.chat.sessions = [session, ...state.chat.sessions];state.chat.activeId = session.id;state.chat.revision = session.revision;
  }
  const { options, assistant, messages } = retry ? prepareRetryTurn(state.chat.messages,state.chat.options,state.snapshot?.settings) : prepareChatTurn(state.chat, message, state.snapshot?.settings);
  state.chat.messages = messages;
  state.chat.streaming = true;
  state.chat.controller = new AbortController();
  renderCurrentPreservingDraft(retry ? null : message);
  const started = performance.now();
  try {
    await api.streamChat(chatRequest(state.snapshot?.engine?.model,state.chat.messages.slice(0,-1),options), {
      signal:state.chat.controller.signal,
      onReasoning(delta) {
        assistant.reasoning += delta;
        const body = document.querySelector('#chat-messages .tf-message:last-child .tf-message-body');
        if (body && !assistant.content) body.textContent = t('正在思考…');
      },
      onToolCalls(calls) {
        for (const delta of calls) {
          if (!Number.isInteger(delta.index) || delta.index < 0 || delta.index >= 64) throw new Error(t('无效工具调用索引'));
          const item = assistant.tool_calls[delta.index] ?? {id:'',type:'function',function:{name:'',arguments:''}};
          if (delta.id) item.id = delta.id;
          if (delta.function?.name) item.function.name += delta.function.name;
          if (delta.function?.arguments) item.function.arguments += delta.function.arguments;
          if (item.function.arguments.length > 1048576) throw new Error(t('工具参数过长'));
          assistant.tool_calls[delta.index] = item;
        }
      },
      onUsage(event) { assistant.metrics = {...event.usage,...event.tensorfold}; },
      onDelta(delta) {
        assistant.content += delta;
        const body = document.querySelector('#chat-messages .tf-message:last-child .tf-message-body');
        const box = document.querySelector('#chat-messages');
        const follow = box && box.scrollHeight - box.scrollTop - box.clientHeight < 120;
        if (body) body.innerHTML = renderChatMarkdown(assistant.content);
        if (follow) box.scrollTop = box.scrollHeight;
      },
    });
    assistant.status = 'completed';
  } catch (error) {
    assistant.status = error.name === 'AbortError' ? 'cancelled' : 'failed';
    if (error.name !== 'AbortError') {
      assistant.error = error.message;
      throw error;
    }
    assistant.content ||= t('生成已取消。');
  } finally {
    assistant.metrics = {...assistant.metrics,elapsed_seconds:(performance.now()-started)/1000};
    state.chat.streaming = false;
    state.chat.controller = null;
    await persistChat();
  }
}

async function handleForm(form) {
  const action = form.dataset.form;
  const values = formValues(form);
  if (action === 'chat-settings') { state.chat.options = parseChatOptions(values,state.snapshot?.settings); toast(t('生成设置已应用')); return; }
  if (action === 'chat-rename') {
    const session = await api.request(`/api/chat/sessions/${encodeURIComponent(state.chat.activeId)}`, { method:'PUT', body:{ revision:state.chat.revision,title:values.title } });
    state.chat.revision = session.revision;
    state.chat.sessions = [session,...state.chat.sessions.filter((item) => item.id !== session.id)];
    closeModal();renderCurrent();return;
  }
  if (action === 'settings-save') return run('设置已保存', () => api.request('/api/settings', { method:'PUT', body:serializeSettings(values) }));
  if (action === 'model-config-save') {
    const model = values.model;
    const config = serializeSettings(values);
    const result = await run('模型配置已保存', () => api.request('/api/models/config', { method:'PUT', body:{ model, config } }));
    closeModal();
    return result;
  }
  if (action === 'profile-create') {
    const model = state.snapshot?.models?.find((item) => item.id === values.model);
    const result = await run('配置档已保存', () => api.request('/api/profiles', { method:'POST', body:{ name:values.name, model:values.model, config:model?.config ?? {} } }));
    refreshModelConfigModal();
    return result;
  }
  if (action === 'profile-import') {
    let parsed;
    try { parsed = JSON.parse(values.json); } catch { throw new Error(t('配置档 JSON 格式无效')); }
    const profile = parsed?.profile ?? parsed;
    if (!profile || typeof profile.name !== 'string' || !profile.name.trim()) throw new Error(t('配置档缺少名称'));
    const { settings } = partitionProfileConfig(profile.config ?? {});
    const result = await run('配置档已导入', () => api.request('/api/profiles', { method:'POST', body:{ name:profile.name.trim(), config:settings } }));
    refreshModelConfigModal();
    return result;
  }
  if (action === 'download-create') {
    const request = catalogDownloadRequest(state.pageData.catalog, values.catalog_model);
    return run('下载任务已创建', () => api.request(request.path, request.options));
  }
  if (action === 'stats-filter') {
    state.filters.statsModel = values.model;
    state.filters.statsRange = values.range;
    return loadPageData('overview');
  }
  if (action === 'logs-filter') {
    state.filters.logLevel = values.level;
    state.filters.logQuery = values.query;
    state.filters.logLimit = values.limit;
    return loadPageData('activity');
  }
  if (action === 'key-create') {
    const result = await run('密钥已创建，只展示这一次', () => api.request('/api/keys', { method:'POST', body:{ name:values.name, expires_days:Number(values.expires_days) } }));
    const plaintext = result.key ?? result.token ?? result.api_key;
    showModal('请立即保存 API Key', plaintext ? `<p class="tf-note warn">${t('关闭后无法再次查看。')}</p><textarea readonly>${escapeHtml(plaintext)}</textarea>` : `<p class="tf-note warn">${t('服务未返回明文密钥，请撤销该记录后重试。')}</p>`);
    return;
  }
  if (action === 'benchmark-run') return run('基准任务已提交', () => api.request('/api/benchmark', { method:'POST', body:benchmarkRequest(values.tier, values) }));
  if (action === 'service-switch') {
    if (!confirm(t('停止所选已识别服务，等待端点和内存释放，再启动目标模型 {model}？确认快照最多有效 30 秒；超时不会强杀。', { model:values.model }))) return;
    const request = serviceSwitchRequest(values.snapshot_id, values.model);
    return run('停止后切换任务已创建', () => api.request(request.path, request.options));
  }
  if (action === 'chat-send') return sendChat(values.message.trim());
}

document.addEventListener('click', (event) => {
  dispatchDocumentClick(event, { navigate, handleAction, onError(error) { if (!error?.reported) toast(error?.message ?? String(error), true); } });
});

for (const type of ['input', 'change']) pageElement.addEventListener(type, (event) => {
  if (event.target?.matches?.('[data-role="engine-model"]')) state.launchTarget = event.target.value;
  if (isPollEditingTarget(event.target)) pageDirty = true;
});

pageElement.addEventListener('keydown', (event) => {
  if (event.target?.id !== 'chat-input' || !isChatSubmitKey(event, { streaming:state.chat.streaming || state.chat.submitting })) return;
  event.preventDefault();
  event.target.form?.requestSubmit();
});
pageElement.addEventListener('input', (event) => {
  if (event.target?.id !== 'model-search') return;
  state.modelSearch = event.target.value;
  renderCurrentPreservingDraft();
});
pageElement.addEventListener('input', (event) => {
  if (event.target?.id !== 'chat-search') return;
  const query = event.target.value.trim().toLocaleLowerCase();
  pageElement.querySelectorAll('.tf-chat-session').forEach((item) => { item.hidden = !item.textContent.toLocaleLowerCase().includes(query); });
});

document.addEventListener('submit', (event) => {
  const form = event.target.closest('[data-form]');
  if (!form) return;
  event.preventDefault();
  handleForm(form).catch((error) => toast(error.message ?? String(error), true));
});

document.querySelector('#language-toggle').addEventListener('click', () => {
  applyLanguage(getLocale() === 'zh-CN' ? 'en' : 'zh-CN');
});

window.addEventListener('hashchange', async () => {
  routeFromHash();
  try {
    await loadPageData(state.page, { render:false });
    renderCurrent();
  } catch (error) {
    toast(error.message ?? String(error), true);
    renderCurrent();
  }
});

async function initialize() {
  routeFromHash();
  try {
    await getAdminToken();
    applyLanguage(getBootstrapLanguage() ?? getLocale());
    await refreshSnapshot({ render:false });
    await loadPageData(state.page, { render:false });
    renderCurrent();
    setInterval(async () => {
      try {
        await refreshSnapshot({ render:false });
        const polledPage = state.page;
        const editing = isPollEditingTarget(document.activeElement);
        if (shouldPollLivePage(polledPage, { editing, dirty:pageDirty, streaming:state.chat.streaming })) {
          await loadPageData(polledPage, { render:false });
          const stillEditing = isPollEditingTarget(document.activeElement);
          if (state.page === polledPage && shouldPollLivePage(polledPage, { editing:stillEditing, dirty:pageDirty, streaming:state.chat.streaming })) renderCurrent();
        }
        document.querySelector('#poll-status').textContent = '';
      } catch (error) {
        document.querySelector('#poll-status').textContent = t('刷新失败：{message}', { message:error.message });
      }
    }, 3000);
  } catch (error) {
    renderFatal(error);
  }
}

initialize();
