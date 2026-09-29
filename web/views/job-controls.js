import { h } from './shared.js';

export function renderJobActions(job) {
  const value = (verb) => `${job.id}:${verb}`;
  const pausable = ['download', 'test', 'accuracy'].includes(job.kind);
  if (job.status === 'running') {
    return `${pausable ? h.button('暂停', 'job-action', value('pause'), 'compact') : ''}${!['activate', 'rollback'].includes(job.kind) ? h.button('取消', 'job-action', value('cancel'), 'compact danger') : ''}`;
  }
  if (job.status === 'paused') return `${h.button('继续', 'job-action', value('resume'), 'compact primary')}${h.button('取消', 'job-action', value('cancel'), 'compact danger')}`;
  if (['failed', 'cancelled', 'interrupted'].includes(job.status)) return h.button('重试', 'job-action', value('retry'), 'compact');
  return '';
}

export function jobDetails(job) {
  return `${h.kv('任务类型', job.kind)}${h.kv('状态', job.status)}${h.kv('参数', Object.keys(job.params ?? {}).length ? JSON.stringify(job.params) : null)}${h.kv('进度', job.progress == null ? null : JSON.stringify(job.progress))}${h.kv('错误', job.error)}`;
}
