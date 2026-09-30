import { h, escapeHtml, formatBytes } from './shared.js';
import { renderResources, renderServiceControls } from './resources.js';
import { getLocale, t } from '../i18n.js';

function formatTimestamp(value) {
  if (value === null || value === undefined || value === '') return value;
  const numeric = Number(value);
  const parsed = Number.isFinite(numeric)
    ? new Date(Math.abs(numeric) < 1e12 ? numeric * 1000 : numeric)
    : new Date(value);
  return Number.isNaN(parsed.getTime()) ? value : parsed.toLocaleString(getLocale());
}

export function chooseLaunchModel(snapshot = {}) {
  const options = (snapshot.models ?? []).filter((model) => model.installed === true && model.startable === true);
  const preferred = [snapshot.settings?.selected_model, snapshot.engine?.model].filter(Boolean);
  const selectedModel = preferred.map((value) => options.find((model) => model.id === value || model.repo === value)).find(Boolean) ?? options[0];
  return { options, selected:selectedModel?.id ?? '' };
}

export function getLaunchGate(snapshot = {}, selected = '') {
  if (!snapshot.update?.active) return { allowed:false, reason:t('请先安装 TensorFold 引擎') };
  if (!selected) return { allowed:false, reason:t('请先选择已通过当前引擎检测的模型') };
  return { allowed:true, reason:'' };
}

export function renderOverview(state) {
  const snapshot = state.snapshot ?? {};
  const engine = snapshot.engine ?? {};
  const settings = snapshot.settings ?? {};
  const stats = state.pageData.stats ?? snapshot.stats ?? {};
  const usage = stats.total ?? {};
  const system = snapshot.system ?? {};
  const engineMemory = engine.health_detail?.memory ?? {};
  const engineFootprint = engineMemory.footprint ?? engineMemory.footprint_bytes;
  const isReady = engine.state === 'ready';
  const isAttached = engine.state === 'attached' || engine.control_owner === 'external';
  const isOwned = engine.control_owner === 'manager';
  const childExitConfirmed = engine.child_exit_confirmed === true;
  const launchModel = chooseLaunchModel(snapshot);
  const selected = launchModel.selected;
  const launchGate = getLaunchGate(snapshot, selected);
  const unavailableCount = (snapshot.models ?? []).filter((model) => model.installed && model.startable !== true).length;
  const installLink = !snapshot.update?.active ? h.button('安装引擎 →', 'goto', 'updates') : '';
  const forceRequired = isOwned && !childExitConfirmed && engine.state === 'failed' && /force|强制/i.test(engine.error ?? '');
  const ownedCanStop = isOwned && !childExitConfirmed && ['starting', 'ready', 'failed', 'restarting', 'stopping'].includes(engine.state);
  const engineAction = isAttached
    ? h.button('断开连接', 'engine-detach', '', 'danger')
    : forceRequired
      ? h.button('强制停止自有服务', 'engine-force-stop', '', 'danger')
      : ownedCanStop
        ? h.button('停止服务', 'engine-stop', '', 'danger', engine.state === 'stopping' ? t('停止请求处理中') : '')
        : h.button('启动服务', 'engine-start', selected, 'primary', launchGate.reason);
  const restart = isOwned && (isReady || (engine.state === 'failed' && childExitConfirmed))
    ? h.button('重启', 'engine-restart', selected, '', !launchGate.allowed ? launchGate.reason : '')
    : '';
  const rows = stats.requests ?? stats.items ?? [];
  return h.heading('运行总览', '服务状态与本机用量。', `<div class="tf-actions">${installLink}${restart}${engineAction}</div>`)
    + h.card(t('推理服务 · {state}', { state:engine.state ?? t('未知') }), `<div class="tf-overview-primary">${h.kv('运行模型', engine.model)}${h.kv('运行时版本', engine.version)}${h.kv('可回收 / 可用内存', formatBytes(snapshot.resources?.memory?.available_bytes))}${h.kv('内存压力', snapshot.resources?.memory?.pressure)}</div>${engine.error ? `<div class="tf-alert">${h.kv('最近错误', engine.error)}</div>` : ''}${unavailableCount ? h.note(t('另有 {count} 个已安装模型尚未通过当前引擎的离线启动检测，已从启动候选中排除。', { count:unavailableCount }), true) : ''}`, launchModel.options.length ? `<label class="sr-only" for="overview-model">${t('启动模型')}</label><select id="overview-model" data-role="engine-model">${launchModel.options.map((model) => `<option value="${escapeHtml(model.id)}"${model.id === selected ? ' selected' : ''}>${escapeHtml(model.name ?? model.id)}</option>`).join('')}</select>` : '')
    + `<div class="tf-metrics tf-overview-metrics">${h.metric('请求数', usage.requests ?? stats.requests_count ?? stats.total_requests)}${h.metric('输入 tokens', usage.input_tokens ?? stats.input_tokens)}${h.metric('输出 tokens', usage.output_tokens ?? stats.output_tokens)}${h.metric('引擎内存', formatBytes(engineFootprint), '上游 health 实际采样')}</div>`
    + h.card('统计与用量', `<form class="tf-overview-filters" data-form="stats-filter">${h.select('模型', 'model', [['', t('全部模型')], ...(snapshot.models ?? []).map((model) => [model.id, model.name ?? model.id])], state.filters?.statsModel ?? '')}${h.select('时间范围', 'range', [['24h', t('最近 24 小时')], ['7d', t('最近 7 天')], ['30d', t('最近 30 天')], ['all', t('全部')]], state.filters?.statsRange ?? '24h')}<button type="submit">${t('查询')}</button>${h.button('导出 CSV', 'stats-export')}</form><details class="tf-disclosure"><summary>${t('请求明细')}</summary>${h.table(['时间','模型','状态','输入 tokens','输出 tokens','总耗时'], rows.slice(0,20).map((item) => [item.at,item.model,item.status,item.input_tokens,item.output_tokens,item.elapsed]))}</details>`)
    + `<details class="tf-disclosure"><summary>${t('运行诊断与外部服务')}</summary>${h.card('运行细节', `${h.kv('进程 PID', engine.pid)}${h.kv('启动时间', formatTimestamp(engine.started_at))}${h.kv('待应用配置', engine.pending)}${h.kv('主机内存', formatBytes(system.memory_total_bytes))}${h.kv('上下文', settings.context)}${h.kv('最大生成 tokens', settings.max_tokens)}`)}${renderResources(snapshot.resources)}${renderServiceControls(state.pageData.services, snapshot.models, snapshot.jobs, engine)}</details>`;
}
