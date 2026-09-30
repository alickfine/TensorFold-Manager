import { h, html, formatBytes } from './shared.js';
import { jobDetails, renderJobActions } from './job-controls.js';
import { t } from '../i18n.js';

const DOWNLOAD_SOURCES = new Set(['huggingface', 'hf-mirror', 'modelscope']);

function sourceName(source) {
  if (source === 'modelscope') return 'ModelScope';
  if (source === 'hf-mirror') return t('HF 镜像');
  return 'Hugging Face';
}

export function supportedCatalogEntries(catalog = {}) {
  const entries = Array.isArray(catalog.models) ? catalog.models : [];
  return entries.flatMap((item) => {
    if (item?.supported !== true || !item.repo) return [];
    const sources = item.download_sources ?? [item.source ?? 'huggingface'];
    return sources.filter((source) => DOWNLOAD_SOURCES.has(source)).map((source) => ({ ...item, source }));
  });
}

export function revisionKindLabel(kind) {
  if (kind === 'repository_commit') return t('仓库提交');
  if (kind === 'file_manifest_sha256') return t('文件树快照');
  return kind ?? null;
}

export function renderDownloads(state) {
  const catalog = state.pageData.catalog ?? {};
  const jobs = (state.pageData.jobs?.jobs ?? state.snapshot?.jobs ?? []).filter((job) => job.kind === 'download');
  const catalogRows = supportedCatalogEntries(catalog);
  const choices = catalogRows.map((item) => {
    const source = item.source ?? 'huggingface';
    return [`${source}:${item.repo}`, `${item.name ?? item.repo} · ${sourceName(source)}`];
  });
  return h.heading('模型下载器', '选择 TensorFold 已确认支持的模型，并从对应官方模型库直接下载。')
    + h.card('新建下载', `<form data-form="download-create"><div class="tf-form-grid">${h.select('受支持模型与来源', 'catalog_model', choices.length ? choices : [['', t('暂无可下载的受支持模型')]], '', { full:true, hint:'仓库、版本与受管目录由后端支持目录确定' })}</div><div class="tf-actions form-actions"><button type="submit" class="primary"${choices.length ? '' : ` disabled title="${t('暂无可下载的受支持模型')}"`}>${t('开始下载')}</button></div></form>`)
    + h.card('支持目录', h.table(['模型', '模型库', '仓库', '版本'], catalogRows.map((item) => [item.name ?? item.id, sourceName(item.source), item.repo, item.revision ?? t('由模型库解析')]), '暂无可下载的受支持模型'))
    + h.card('下载任务', jobs.length ? jobs.map((job) => {
      const progress = job.progress ?? {};
      const ratio = progress.total_bytes ? Math.min(100, progress.downloaded_bytes / progress.total_bytes * 100) : null;
      const bar = ratio == null ? '' : `<progress max="100" value="${ratio}"></progress><div class="tf-sub">${ratio.toFixed(1)}% · ${formatBytes(progress.downloaded_bytes)} / ${formatBytes(progress.total_bytes)}</div>`;
      const identity = job.result ?? progress;
      return `<div class="tf-download-job"><div class="tf-row"><div><strong>${h.tag(job.params?.repo ?? job.kind ?? job.id, 'blue')}</strong><div class="tf-sub">${jobDetails(job)}${h.kv('来源', job.params?.source)}${h.kv('Revision', identity.revision)}${h.kv('身份类型', revisionKindLabel(identity.revision_kind))}</div></div><div class="tf-actions">${renderJobActions(job)}</div></div>${bar}</div>`;
    }).join('') : `<div class="tf-empty">${t('暂无任务')}</div>`);
}
