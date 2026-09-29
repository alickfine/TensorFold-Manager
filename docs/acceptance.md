# TensorFold Manager 验收记录

**简体中文** | [English](acceptance.en.md)

版本：0.1.0-alpha.1，Apple Silicon 测试版。用户安装验收尚待反馈。

## 已验证（2026-09-29，macOS 27 / arm64 / 256 GiB）

| 项目 | 实际结果 |
|---|---|
| 自动化回归 | Python 149 项、Web 38 项；原生 bootstrap、精确 origin、导出、凭据范围及运行时完整性检查通过 |
| 原生 App | AppKit + WKWebView，实际管理服务启动；管理令牌仅保存在页面模块闭包 |
| 引擎安装 | 官方 v0.3.6.1 / v0.3.6.2 固定提交、独立环境，实际 CLI / HTTP 推理验证 |
| 模型下载 | Gemma 官方固定 revision，12 文件 / 15,373,588,575 bytes，逐文件摘要校验后完成；ModelScope 文件树及 config 实际验证 |
| 聊天 | 本地 Qwen、下载的 Gemma 实际推理；Gemma 中文回答及关闭 thinking 的参数映射验证 |
| 最终安装版切换 | Gemma → Qwen → Gemma 均就绪；旧 PID 退出后加载目标，Qwen 内置聊天返回 2，正常退出后所有验收 PID 和 18080 端口释放 |
| API 网关 | 真实量化模型：无密钥请求 401，隔离验收数据中的一次性测试密钥请求 200、回答 2；测试密钥随后移除 |
| 基准 / 参考答案 | 两次真实基准请求完成；1+1 参考测试实际返回 2、通过。评分仅为参考文本一致性 |
| 统计 / 缓存 | 网关真实请求指标、上游 health 实际 active / cache / peak / footprint；无来源的指标显示未采集 |
| 量化 | 真实 Gemma 4 bit / group 64 经两阶段转换为 4 bit / group 32，bfloat16 scales；源文件指纹不变、中间目录清理、实际加载及推理返回 2 |
| 工具 / 凭据 | 原生 App 实际安装 mlx-lm 0.31.3 + HF Hub 1.33.0；系统凭据助手返回三个独立账户的 configured 状态，未读写既有 token |
| 升级 / 回退 | 真实 v0.3.6.1 → v0.3.6.2 → v0.3.6.1，旧 PID 退出后启动新进程，两版真实请求均返回 2 |
| 失败恢复 / 竞争 | 候选失败后旧环境恢复且实际 fixture HTTP 请求通过；activate / rollback 成功及失败恢复全过程 OS 租约竞争测试通过 |
| 表单刷新 | 原生 App 修改端口后失焦、多轮轮询，未保存输入仍保留；取消确认不执行停止 |
| 安装包 | 实际构建 DMG、只读挂载、复制 App、卸载镜像后启动，严格签名验证通过；带空格路径也已验证 |
| 退出 | 正常退出 App 后其所属引擎 PID 消失、端口关闭；卡住退出的显式等待 / 强制选项已实际验证 |

## 内存和服务边界

- 启动前重新采样 macOS 可回收内存与压力，按权重、KV、并发、草稿、缓存和工作区保守预算，预留系统容量。未知预算拒绝启动，RSS 不作为峰值预算。
- 全局 OS 重任务租约覆盖推理、量化、切换、升级及失败恢复。关闭旧模型并确认子进程退出后，重新检查可用内存再加载。
- 同用户、完整参数匹配的 TensorFold 服务支持经过进程身份核验的只读复用。oMLX 和不兼容服务会阻止新的重任务；停止它们须经界面确认、30 秒一次性实例快照和原实例验证。
- 外部控制仅发送正常终止；等待端点和内存释放，超时不会强杀或追逐重新拉起的新 PID。本次没有停止用户既有外部服务。
- 本机约 169 GiB 的 GLM 权重在保守预算下超出系统预留后的容量，实际被门禁拒绝；没有为启动它降低预算。

## 限制和披露

- Ad hoc 签名，未 Apple Developer ID 签名 / 公证，不能声称已通过 Gatekeeper。目标系统 macOS 14+；实际业务验证在 macOS 27 完成。
- 主引擎与模型首次安装需要联网，模型独立下载，不包含在 DMG 中。已知支持 checkpoint 以当前上游和实际 CLI 预检为准。
- 量化目标来自当前引擎的 config 预检；实际权重在完成转换后再检验，不能把配置预检当成运行保证。转换产物需要在模型库执行兼容验证后使用。
- HF 上传经过仓库实际可见性、文件范围和摘要预览再确认。范围 / 凭据 / 变更拒绝由 fixture 验证；没有用户 token，本次未向 HF 发布真实模型，也未写入真实 provider 凭据。
- ModelScope 无全仓不可变提交时采用逐文件 immutable revision，界面标为文件树快照；不把 master 当作固定版本。
- GitHub 匿名 API 在密集验收中实际触发限流；界面保留失败原因。版本切换测试的官方 tag / commit 额外通过已登录的 gh 只读核对，App 不读取 gh 凭据。
- TensorFold 未提供的 oMLX 专属能力、音视频、embedding、ANE 等显示明确不可用原因；不展示模拟运行指标。
- 独立审查发现的未保存表单和升级租约空窗已修复并加入回归。后续多 agent 复审遇到账号用量限制，由主线程接手实际验证。

## 公开安装包验收

- [GitHub CI](https://github.com/alickfine/TensorFold-Manager/actions/runs/36510596995) 全部通过：macOS 14 arm64 运行器，149 Python / 38 Web 测试与原生检查、DMG 构建、附件上传、Release 发布成功。
- [v0.1.0-alpha.1 Release](https://github.com/alickfine/TensorFold-Manager/releases/tag/v0.1.0-alpha.1) 已公开，包含 DMG 和 SHA256SUMS.txt。
- 实际从该 Release 下载 DMG，摘要与文件、GitHub asset digest 一致：`2a9a717b8fa3639a64f8564c9757186026ec8c1b87b7fea7e03fb4e614ec54cf`。
- 公开 DMG 的 manager / Web 源文件与已验证源码逐字节一致。实际只读挂载、复制、卸载后启动，Gemma 就绪、内置聊天回答 2+2=4；正常退出后引擎 PID 消失、端口关闭，严格签名检查通过。
- 当前实现和安装包的开发方验收完成；用户验收意见、真实 provider 凭据 / HF 上传以及 Apple 公证分别按上述边界处理。

## alpha.2 双语迭代验收（2026-09-29）

- GitHub 中文首页、英文 README、双语 Release 说明及中英文验收记录已完成。
- 新鲜回归：149 Python、48 Web 测试及 9 项原生 bootstrap/origin/export/language 检查和凭据、运行时完整性检查通过。
- 实际 alpha.2 App：中文 → 英文 → 中文，17 页面英文渲染由回归覆盖，导航、菜单和原生确认框实际切换。取消缓存清理后未执行清理。
- 未保存端口 18081 在语言切换后保留；没有保存该测试值。已有聊天原文保留，未发送草稿“运行总览 保存 bilingual 验收”切换后保持原样。未加载新模型。
- 英文退出重启后管理端口由 63491 改为 63975，界面与原生菜单仍为英文；改回中文再次重启端口为 64126，中文偏好保持。验收后退出 App。
- 量化页不同模型格式联动恢复、英文本地校验错误有专项回归；独立复审两项修复通过。
- 本地 alpha.2 DMG 构建成功；App 严格签名验证通过，ad hoc / 未 Apple 公证。公开安装包已按下述记录验收。

- 公开 [alpha.2 CI](https://github.com/alickfine/TensorFold-Manager/actions/runs/36513259885) 全部通过，149 Python / 48 Web / 原生检查、构建与发布均成功。
- 从 [alpha.2 Release](https://github.com/alickfine/TensorFold-Manager/releases/tag/v0.1.0-alpha.2) 下载 DMG，SHA256 与文件清单和 GitHub digest 一致：`a080d5a66ade9c6c2b22371d94a23d0dfb2a19e7c9c762957ce20fd359ae5789`。
- 只读挂载、复制、卸载后实际启动公开 App；manager / Web 源码与已验证源码逐字节一致、版本正确、严格签名通过。中文与英文页面及原生菜单实际切换，验收后恢复中文并正常退出，管理进程消失、65085 端口关闭。
