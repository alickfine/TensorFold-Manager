import { t } from './i18n.js';

const exactRepo = /^[A-Za-z0-9][A-Za-z0-9._-]*\/[A-Za-z0-9][A-Za-z0-9._-]*$/;
const providers = new Set(['hf-download', 'hf-upload', 'modelscope-download']);
const livePollPages = new Set([
  'overview', 'models', 'downloads', 'updates',
  'stats', 'cache', 'logs', 'benchmark', 'server', 'api',
]);

export function shouldPollLivePage(page, { editing = false, dirty = false, streaming = false } = {}) {
  return !editing && !dirty && !streaming && livePollPages.has(page);
}

export function isPollEditingTarget(element) {
  if (!element) return false;
  const tagName = String(element.tagName ?? '').toLowerCase();
  if (['input', 'select', 'textarea'].includes(tagName) || element.isContentEditable === true) return true;
  return Boolean(element.closest?.('form, [contenteditable]:not([contenteditable="false"])'));
}

export function assertChatCanSubmit(streaming) {
  if (streaming === true) throw new Error(t('当前生成尚未结束'));
}

export function isChatSubmitKey(event, { streaming = false } = {}) {
  return streaming !== true && event?.key === 'Enter' && event.shiftKey !== true && event.isComposing !== true;
}

function post(path, body = {}) {
  return { path, options:{ method:'POST', body } };
}

export function serviceSwitchRequest(snapshotId, model) {
  if (!snapshotId || !model) throw new TypeError(t('请选择仍在有效期内的服务快照和目标模型'));
  return post('/api/services/switch', { snapshot_id:snapshotId, model, confirm:true });
}

export function engineStopRequest(force = false) {
  return post('/api/engine/stop', { force:force === true });
}

export function engineDetachRequest() {
  return post('/api/engine/detach');
}

export function credentialRequest(provider, token) {
  if (!providers.has(provider)) throw new TypeError(t('未知凭据类型'));
  if (typeof token !== 'string' || !token) throw new TypeError(t('请输入凭据'));
  return { path:`/api/credentials/${provider}`, options:{ method:'PUT', body:{ token } } };
}

export function credentialDeleteRequest(provider) {
  if (!providers.has(provider)) throw new TypeError(t('未知凭据类型'));
  return { path:`/api/credentials/${provider}`, options:{ method:'DELETE' } };
}

export function quantizeRequest(values) {
  const bits = Number(values.bits);
  const groupSize = Number(values.group_size);
  if (![2, 3, 4, 6, 8].includes(bits)) throw new TypeError(t('量化位宽无效'));
  if (![32, 64, 128].includes(groupSize)) throw new TypeError(t('group size 无效'));
  if (values.mode !== 'affine') throw new TypeError(t('当前只支持 affine 量化'));
  const body = { model:values.model, name:String(values.name ?? '').trim(), bits, group_size:groupSize, mode:'affine' };
  if (!body.name) delete body.name;
  return post('/api/tools/quantize', body);
}

export function uploadPrepareRequest(values) {
  if (!exactRepo.test(values.repo ?? '') || values.repo.includes('..')) throw new TypeError(t('仓库必须是精确的 owner/model 标识'));
  if (!['public', 'private'].includes(values.visibility)) throw new TypeError(t('请选择仓库可见性'));
  return post('/api/tools/uploads/prepare', { model:values.model, repo:values.repo, visibility:values.visibility });
}

export function uploadConfirmRequest(planId) {
  if (!planId) throw new TypeError(t('上传预览已失效，请重新准备'));
  return post('/api/tools/uploads/confirm', { plan_id:planId, confirm:true });
}

export function downloadRequest(values) {
  if (!exactRepo.test(values.repo ?? '') || values.repo.includes('..')) throw new TypeError(t('仓库必须是精确的 owner/model 标识'));
  const source = values.source || 'huggingface';
  const useCredentials = values.use_credentials === true || values.use_credentials === 'on' || values.use_credentials === 'true';
  if (source === 'hf-mirror' && useCredentials) throw new TypeError(t('第三方镜像不能接收 App 凭据'));
  const revision = String(values.revision ?? '').trim() || (source === 'modelscope' ? 'master' : 'main');
  return post('/api/downloads', {
    repo:values.repo,
    source,
    revision,
    directory:values.directory,
    use_credentials:useCredentials,
  });
}

export function catalogDownloadRequest(catalog = {}, selection = '', { useCredentials = false } = {}) {
  const models = Array.isArray(catalog.models) ? catalog.models : [];
  const separator = selection.indexOf(':');
  const source = separator > 0 ? selection.slice(0, separator) : '';
  const repo = separator > 0 ? selection.slice(separator + 1) : '';
  const item = models.find((model) => model.repo === repo);
  const sources = item?.download_sources ?? [item?.source ?? 'huggingface'];
  if (!item || item.supported !== true || !sources.includes(source) || !['huggingface', 'hf-mirror', 'modelscope'].includes(source)) {
    throw new TypeError(t('请选择目录中的受支持模型'));
  }
  return downloadRequest({
    repo:item.repo,
    source,
    revision:item.revision ?? '',
    directory:catalog.default_directory,
    use_credentials:useCredentials,
  });
}

export async function optionalCredentialStatus(request, previous = null) {
  if (previous?.unavailable_reason) return previous;
  try {
    return await request('/api/credentials');
  } catch (error) {
    if (error?.code !== 'credential_helper_unavailable') throw error;
    return { providers:{}, unavailable_reason:error.message };
  }
}
