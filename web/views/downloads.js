import { h, html, formatBytes } from './shared.js';

function jobActions(job) {
  if (job.status === 'running' && job.kind === 'download') return `${h.button('暂停', 'job-action', `${job.id}:pause`, 'compact')}${h.button('取消', 'job-action', `${job.id}:cancel`, 'compact danger')}`;
  if (job.status === 'running' && !['activate', 'rollback'].includes(job.kind)) return h.button('取消', 'job-action', `${job.id}:cancel`, 'compact danger');
  if (job.status === 'paused') return `${h.button('继续', 'job-action', `${job.id}:resume`, 'compact primary')}${h.button('取消', 'job-action', `${job.id}:cancel`, 'compact danger')}`;
  if (['failed', 'cancelled', 'interrupted'].includes(job.status)) return h.button('重试', 'job-action', `${job.id}:retry`, 'compact');
  return '';
}

export function renderDownloads(state) {
  const catalog = state.pageData.catalog?.models ?? state.pageData.catalog?.items ?? state.pageData.catalog ?? [];
  const jobs = state.pageData.jobs?.jobs ?? state.snapshot?.jobs ?? [];
  const catalogRows = Array.isArray(catalog) ? catalog : [];
  const sourceOptions = (state.pageData.catalog?.sources ?? []).map((source) => [source.id, `${source.id}${source.third_party ? '（第三方）' : ''}`]);
  const defaultDirectory = state.pageData.catalog?.default_directory ?? '';
  const revisionPolicy = `${state.pageData.catalog?.revision_policy ?? '必须解析为不可变 commit'}。ModelScope 必须直接填写 40–64 位 commit SHA；不按相似名称猜测映射。`;
  return h.heading('模型下载器', '创建有固定来源、revision 和受管目标目录的可恢复任务。', h.button('刷新任务', 'load-page', 'downloads'))
    + h.card('新建下载', h.form('download-create',
      h.field('仓库 ID', 'repo', '', { required:true, hint:'namespace/repository' })
      + h.select('来源', 'source', sourceOptions.length ? sourceOptions : [['huggingface', 'Hugging Face'], ['hf-mirror', 'HF 镜像（第三方）'], ['modelscope', 'ModelScope']], 'huggingface')
      + h.field('不可变 revision SHA', 'revision', '', { required:true, hint:revisionPolicy })
      + h.field('目标目录', 'directory', defaultDirectory, { required:true, hint:'更改默认目录会先请求明确写入范围授权' }),
    '创建下载任务'))
    + h.card('来源目录', h.table(['名称', '仓库', '来源', '兼容性', '操作'], catalogRows.map((item) => [item.name ?? item.id, item.repo, item.source, item.supported ? '受支持' : '未确认', html(h.button('填入', 'catalog-select', JSON.stringify({ repo:item.repo, source:item.source }), 'compact'))]), '目录暂无条目；可手动输入经过核验的仓库。'))
    + h.card('下载任务', jobs.length ? jobs.map((job) => {
      const progress = job.progress ?? {};
      const ratio = progress.total_bytes ? Math.min(100, progress.downloaded_bytes / progress.total_bytes * 100) : 0;
      return `<div class="tf-download-job"><div class="tf-row"><div><strong>${h.tag(job.params?.repo ?? job.kind ?? job.id, 'blue')}</strong><div class="tf-sub">${h.kv('任务类型', job.kind)}${h.kv('来源', job.params?.source)}${h.kv('状态', job.status)}${h.kv('错误', job.error)}</div></div><div class="tf-actions">${jobActions(job)}</div></div><progress max="100" value="${ratio}"></progress><div class="tf-sub">${ratio.toFixed(1)}% · ${formatBytes(progress.downloaded_bytes)} / ${formatBytes(progress.total_bytes)}</div></div>`;
    }).join('') : '<div class="tf-empty">暂无下载任务</div>');
}
