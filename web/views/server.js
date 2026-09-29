import { h } from './shared.js';

export function renderServer(state) {
  const settings = state.snapshot?.settings ?? {};
  const system = state.snapshot?.system ?? {};
  return h.heading('服务器与目录', '管理监听端口与受管目录；保存不会接管已占用端口。')
    + `<div class="tf-grid two">${h.card('运行环境', `${h.kv('主机', system.hostname)}${h.kv('平台', system.platform)}${h.kv('架构', system.architecture ?? system.arch)}${h.kv('Python', system.python_version)}${h.kv('运行时目录', system.runtime_path)}`)}${h.card('进程边界', `${h.kv('管理实例', state.snapshot?.instance_id)}${h.kv('引擎 PID', state.snapshot?.engine?.pid)}${h.kv('引擎状态', state.snapshot?.engine?.state)}${h.note('App 自有生命周期由 Manager 管理；外部兼容只读接入；控制外部服务必须走已验证确认切换。')}`)}</div>`
    + h.card('端口与目录', h.form('settings-save',
      h.field('引擎端口', 'engine_port', settings.engine_port ?? '', { type:'number', min:1, max:65535 })
      + h.field('API 网关端口', 'gateway_port', settings.gateway_port ?? '', { type:'number', min:1, max:65535 })
      + h.textarea('模型目录（每行一个）', 'model_dirs', (settings.model_dirs ?? []).join('\n'), { hint:'扫描只读；下载目录由后端验证写入范围。' })
      + h.field('受管快照目录', 'snapshot_dir', settings.snapshot_dir ?? '', { full:true, disabled:true, hint:'安全边界固定为 App 拥有的快照根' }),
    '保存服务器设置'));
}
