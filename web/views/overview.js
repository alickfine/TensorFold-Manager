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
  const options = (snapshot.models ?? []).filter((model) => model.installed === true && model.supported === true);
  const preferred = [snapshot.settings?.selected_model, snapshot.engine?.model].filter(Boolean);
  const selectedModel = preferred.map((value) => options.find((model) => model.id === value || model.repo === value)).find(Boolean) ?? options[0];
  return { options, selected:selectedModel?.id ?? '' };
}

export function getLaunchGate(snapshot = {}, selected = '') {
  if (!snapshot.update?.active) return { allowed:false, reason:t('请先安装 TensorFold 引擎') };
  if (!selected) return { allowed:false, reason:t('请先安装并选择受支持模型') };
  return { allowed:true, reason:'' };
}

export function renderOverview(state) {
  const snapshot = state.snapshot ?? {};
  const engine = snapshot.engine ?? {};
  const settings = snapshot.settings ?? {};
  const stats = snapshot.stats ?? {};
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
  const unsupportedCount = (snapshot.models ?? []).filter((model) => model.installed && !model.supported).length;
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
  return h.heading('运行总览', '从服务状态到每次生成，查看本机推理工作台的真实状态。', `<div class="tf-actions">${installLink}${restart}${engineAction}</div>`)
    + h.card(t('推理服务 · {state}', { state:engine.state ?? t('未知') }), `<div class="tf-chips">${h.tag(engine.model, 'blue')}${h.tag(engine.health, isReady ? 'green' : 'amber')}${h.tag(engine.version)}</div><div class="tf-grid three"><div>${h.kv('进程 PID', engine.pid)}${h.kv('启动时间', formatTimestamp(engine.started_at))}</div><div>${h.kv('运行模型', engine.model)}${h.kv('运行时版本', engine.version)}</div><div>${h.kv('待应用配置', engine.pending)}${h.kv('错误', engine.error)}</div></div>${unsupportedCount ? h.note(t('另有 {count} 个已扫描模型未通过 TensorFold 支持目录门禁，已从启动候选中排除。', { count:unsupportedCount }), true) : ''}`, launchModel.options.length ? `<label class="sr-only" for="overview-model">${t('启动模型')}</label><select id="overview-model" data-role="engine-model">${launchModel.options.map((model) => `<option value="${escapeHtml(model.id)}"${model.id === selected ? ' selected' : ''}>${escapeHtml(model.name ?? model.id)}</option>`).join('')}</select>` : '')
    + `<div class="tf-metrics">${h.metric('累计请求', stats.total?.requests ?? stats.requests, '网关实际记录')}${h.metric('模型数量', snapshot.models?.length, '已扫描目录')}${h.metric('主机内存', formatBytes(system.memory_total_bytes), '系统采集')}${h.metric('引擎内存', formatBytes(engineFootprint), '上游 health 实际采样')}</div>`
    + renderResources(snapshot.resources)
    + renderServiceControls(state.pageData.services, snapshot.models, snapshot.jobs, engine)
    + `<div class="tf-grid two">${h.card('端口与配置', `${h.kv('API 网关', settings.gateway_port)}${h.kv('引擎端口', settings.engine_port)}${h.kv('上下文', settings.context)}${h.kv('最大生成 tokens', settings.max_tokens)}`)}${h.card('版本与管理实例', `${h.kv('Manager 版本', snapshot.app_version)}${h.kv('实例 ID', snapshot.instance_id)}${h.kv('管理服务', location.origin)}${engine.error ? `<div class="tf-alert">${h.kv('最近错误', engine.error)}</div>` : ''}`)}</div>`;
}
