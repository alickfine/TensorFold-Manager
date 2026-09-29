import { h, html, formatBytes } from './shared.js';
import { jobDetails, renderJobActions } from './job-controls.js';
import { t } from '../i18n.js';

export function revisionKindLabel(kind) {
  if (kind === 'repository_commit') return t('仓库提交');
  if (kind === 'file_manifest_sha256') return t('文件树快照');
  return kind ?? null;
}

export function renderDownloads(state) {
  const catalog = state.pageData.catalog?.models ?? state.pageData.catalog?.items ?? state.pageData.catalog ?? [];
  const jobs = state.pageData.jobs?.jobs ?? state.snapshot?.jobs ?? [];
  const catalogRows = Array.isArray(catalog) ? catalog : [];
  const sourceOptions = (state.pageData.catalog?.sources ?? []).map((source) => [source.id, `${source.id}${t(source.third_party ? '（第三方，不发送凭据）' : '（官方来源，可选 App 凭据）')}`]);
  const defaultDirectory = state.pageData.catalog?.default_directory ?? '';
  const revisionPolicy = `${t(state.pageData.catalog?.revision_policy ?? '下载时解析并验证不可变文件身份')}。${t('留空时 Hugging Face 默认 main，ModelScope 默认 master；后者可能记录为逐文件提交组成的“文件树快照”，不冒充仓库提交。')}`;
  const providers = state.pageData.credentials?.providers ?? {};
  const credentialHint = state.pageData.credentials?.unavailable_reason ?? t('Hugging Face：{hf}；ModelScope：{modelscope}。第三方镜像永不发送 App 凭据。', { hf:t(providers['hf-download']?.configured ? '已配置' : '未配置'), modelscope:t(providers['modelscope-download']?.configured ? '已配置' : '未配置') });
  return h.heading('模型下载器', '创建有固定来源、revision 和受管目标目录的可恢复任务。', h.button('刷新任务', 'load-page', 'downloads'))
    + h.card('新建下载', h.form('download-create',
      h.field('仓库 ID', 'repo', '', { required:true, hint:'namespace/repository' })
      + h.select('来源', 'source', sourceOptions.length ? sourceOptions : [['huggingface', 'Hugging Face'], ['hf-mirror', t('HF 镜像（第三方）')], ['modelscope', 'ModelScope']], 'huggingface')
      + h.field('Revision（可留空）', 'revision', '', { hint:revisionPolicy })
      + h.field('目标目录', 'directory', defaultDirectory, { required:true, hint:'更改默认目录会先请求明确写入范围授权' })
      + h.checkbox('使用 App 中已配置的官方来源凭据', 'use_credentials', false, { hint:credentialHint, disabled:Boolean(state.pageData.credentials?.unavailable_reason) }),
    '创建下载任务'))
    + h.card('来源目录', h.table(['名称', '仓库', '来源', '兼容性', '操作'], catalogRows.map((item) => [item.name ?? item.id, item.repo, item.source, t(item.supported ? '受支持' : '未确认'), html(h.button('填入', 'catalog-select', JSON.stringify({ repo:item.repo, source:item.source }), 'compact'))]), '目录暂无条目；可手动输入经过核验的仓库。'))
    + h.card('下载任务', jobs.length ? jobs.map((job) => {
      const progress = job.progress ?? {};
      const ratio = progress.total_bytes ? Math.min(100, progress.downloaded_bytes / progress.total_bytes * 100) : null;
      const bar = ratio == null ? '' : `<progress max="100" value="${ratio}"></progress><div class="tf-sub">${ratio.toFixed(1)}% · ${formatBytes(progress.downloaded_bytes)} / ${formatBytes(progress.total_bytes)}</div>`;
      const identity = job.result ?? progress;
      return `<div class="tf-download-job"><div class="tf-row"><div><strong>${h.tag(job.params?.repo ?? job.kind ?? job.id, 'blue')}</strong><div class="tf-sub">${jobDetails(job)}${h.kv('来源', job.params?.source)}${h.kv('Revision', identity.revision)}${h.kv('身份类型', revisionKindLabel(identity.revision_kind))}</div></div><div class="tf-actions">${renderJobActions(job)}</div></div>${bar}</div>`;
    }).join('') : `<div class="tf-empty">${t('暂无任务')}</div>`);
}
