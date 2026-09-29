import { h, escapeHtml, formatBytes } from './shared.js';
import { renderResources } from './resources.js';

export function chooseLaunchModel(snapshot = {}) {
  const options = (snapshot.models ?? []).filter((model) => model.installed === true && model.supported === true);
  const preferred = [snapshot.settings?.selected_model, snapshot.engine?.model].filter(Boolean);
  const selectedModel = preferred.map((value) => options.find((model) => model.id === value || model.repo === value)).find(Boolean) ?? options[0];
  return { options, selected:selectedModel?.id ?? '' };
}

export function getLaunchGate(snapshot = {}, selected = '') {
  if (!snapshot.update?.active) return { allowed:false, reason:'请先安装 TensorFold 引擎' };
  if (!selected) return { allowed:false, reason:'请先安装并选择受支持模型' };
  return { allowed:true, reason:'' };
}

export function renderOverview(state) {
  const snapshot = state.snapshot ?? {};
  const engine = snapshot.engine ?? {};
  const settings = snapshot.settings ?? {};
  const stats = snapshot.stats ?? {};
  const system = snapshot.system ?? {};
  const isReady = engine.state === 'ready';
  const busy = ['starting', 'stopping', 'restarting'].includes(engine.state);
  const launchModel = chooseLaunchModel(snapshot);
  const selected = launchModel.selected;
  const launchGate = getLaunchGate(snapshot, selected);
  const unsupportedCount = (snapshot.models ?? []).filter((model) => model.installed && !model.supported).length;
  const installLink = !snapshot.update?.active ? h.button('安装引擎 →', 'goto', 'updates') : '';
  const engineAction = isReady
    ? h.button('停止服务', 'engine-stop', '', 'danger', busy ? '服务状态切换中' : '')
    : h.button('启动服务', 'engine-start', selected, 'primary', busy ? '服务状态切换中' : launchGate.reason);
  return h.heading('运行总览', '从服务状态到每次生成，查看本机推理工作台的真实状态。', `<div class="tf-actions">${installLink}${h.button('重启', 'engine-restart', selected, '', !isReady ? '服务未就绪' : (!launchGate.allowed ? launchGate.reason : ''))}${engineAction}</div>`)
    + h.card(`推理服务 · ${engine.state ?? '未知'}`, `<div class="tf-chips">${h.tag(engine.model, 'blue')}${h.tag(engine.health, isReady ? 'green' : 'amber')}${h.tag(engine.version)}</div><div class="tf-grid three"><div>${h.kv('进程 PID', engine.pid)}${h.kv('启动时间', engine.started_at)}</div><div>${h.kv('运行模型', engine.model)}${h.kv('运行时版本', engine.version)}</div><div>${h.kv('待应用配置', engine.pending)}${h.kv('错误', engine.error)}</div></div>${unsupportedCount ? h.note(`另有 ${unsupportedCount} 个已扫描模型未通过 TensorFold 支持目录门禁，已从启动候选中排除。`, true) : ''}`, launchModel.options.length ? `<label class="sr-only" for="overview-model">启动模型</label><select id="overview-model" data-role="engine-model">${launchModel.options.map((model) => `<option value="${escapeHtml(model.id)}"${model.id === selected ? ' selected' : ''}>${escapeHtml(model.name ?? model.id)}</option>`).join('')}</select>` : '')
    + `<div class="tf-metrics">${h.metric('累计请求', stats.total?.requests ?? stats.requests, '网关实际记录')}${h.metric('模型数量', snapshot.models?.length, '已扫描目录')}${h.metric('主机内存', formatBytes(system.memory_total_bytes), '系统采集')}${h.metric('运行内存', formatBytes(system.memory_used_bytes), '系统采集')}</div>`
    + renderResources(snapshot.resources)
    + `<div class="tf-grid two">${h.card('端口与配置', `${h.kv('API 网关', settings.gateway_port)}${h.kv('引擎端口', settings.engine_port)}${h.kv('上下文', settings.context)}${h.kv('最大生成 tokens', settings.max_tokens)}`)}${h.card('版本与管理实例', `${h.kv('Manager 版本', snapshot.app_version)}${h.kv('实例 ID', snapshot.instance_id)}${h.kv('管理服务', location.origin)}${engine.error ? `<div class="tf-alert">${h.kv('最近错误', engine.error)}</div>` : ''}`)}</div>`;
}
