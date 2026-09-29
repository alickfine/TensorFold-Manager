# TensorFold Manager design

批准依据：用户验收 prototype v0.2 后于 2026-09-29 明确开工；项目名 TensorFold Manager。自动检查更新、手动升级、失败回退已确认。

## 产品与交付
独立 macOS Apple Silicon App，内置 Web 管理界面；GitHub alickfine/TensorFold-Manager 公开源代码，Releases 提供真实 DMG、SHA256、版本和签名状态。页面沿用已批准的16模块，不将模拟数据带入正式运行。安装完成后无需系统Python/Node才能打开管理页；推理引擎位于 App 专用可升级环境。上游和App分别版本化，禁止直接更改上游核心。

## 模块
- 总览/统计/缓存：真实health、进程、主机内存、网关请求统计及各模型累计；未采集数据为null/未采集。缓存仅操作本App管理的快照，不能清理oMLX目录或擅自清除现有权重。
- 模型库/下载/配置：扫描用户配置目录与标准目录，精确checkpoint白名单和本地路径。HF、第三方HF mirror、ModelScope明确来源，revision固定和文件身份验证，不自动猜测国内映射。可恢复下载任务、取消/继续/失败原因；profiles和采样设置持久化。
- 工具：量化/上传必须满足后端能力预检；不能适配的oMLX专属内核显示禁用原因，不模拟成功。
- 进程管理：只管理本App启动的子进程；随机可用管理端口，默认网关8080/独立引擎18080，冲突明确提示；启动与健康就绪分离，切换模型先排空请求再重启。用户新增要求允许对已识别、明确确认的外部推理服务进行停止后切换；必须采用 OS 进程实例身份绑定，未知服务或证据不完整时禁用。安全退出时停止自己的服务，只读接入的外部服务不受退出影响。
- API/认证：管理接口受每次启动随机管理凭据保护，密钥不进入仓库/日志。网关默认loopback，API key哈希保存、撤销与过期；下载凭据由Keychain或限定权限的凭据存储负责，不能通过read settings返回。OpenAI chat/completions流式/非流式代理，采集usage/runtime，内置聊天有真正取消、错误反馈和本地历史。
- 配置：保存持久化，明确待重启与实际运行配置；禁止任意shell字符串/路径穿越。动态从上游CLI help提取可用参数；版本适配和能力门禁。
- 更新：每次启动自动检查GitHub，失败保留现有运行；点击升级创建隔离版本环境，CLI/schema/启动/真实API验证通过后切换，失败恢复原环境。引擎下载首次由用户在App点击；本地开发验证可用现有引擎路径，无需改变它。
- 日志/基准/聊天：实际日志脱敏，筛选导出；真实请求测TTFT、prefill、decode、tokens与总耗时，结果历史/准确性队列；不编造官方基准或ANE能力。
- 所有oMLX专属功能在功能适配表逐项说明来源和禁用原因；TensorFold原生不支持图片/音视频/embedding/多模型热加载时不能宣称已支持。

## 验收
从GitHub下载DMG，挂载、安装、启动内嵌Web；真实配置保存重启后存在；用真实本机模型完成启动/就绪、chat API、内置聊天、usage记录、停止、重新启动和模型切换；引擎退出和端口冲突有正确反馈；密钥拒绝未授权请求；下载/升级任务失败不会破坏当前环境；安装包不包含用户凭据、权重或私有数据；披露签名/公证实际状态。

## 安全审查约束（开工前补充）
管理服务固定127.0.0.1；请求Host精确匹配实际端口，拒绝重复Host、恶意域名；Origin存在时必须同源，拒绝null/跨源，无Origin仍认证。无通配CORS；CSP仅self脚本与连接，不允许第三方脚本。WKWebView导航限定实际管理端口；HTTP(S)外链交系统浏览器，其他scheme拒绝。

进程控制只使用当前Popen句柄和独立进程组，不根据磁盘PID或端口发送信号。端口冲突先拒绝再spawn，进程退出后不能靠外部health判断成功。Swift保留stdin父进程管道，Python收到EOF清理自己的引擎（App崩溃同样适用）；无父管道时仅限显式开发模式。上述普通生命周期不操作外部进程；用户新增的外部停止后切换遵循下方专门约束。

启动、停止、升级激活互斥。候选安装在最终槽目录，固定可信upstream release tag/commit；禁止任意包URL。排空超时中止升级；切换前保存旧槽/配置，活动指针原子写入；失败重新启动旧版本并验证真实API恢复。不会并行加载两份大模型进行升级验证。首版SQLite schema向后兼容，升级不迁移破坏旧状态。

扫描目录只读；默认下载写入App专属models根，用户显式选定新目标才写。下载任务私有暂存/manifest，不覆盖已有模型，拒绝穿越和符号链接逃逸；取消只停下载保留可续传文件。清缓存仅App创建且有归属manifest的snapshot根，引擎停止时进行；不能按可编辑路径直接递归删除。来源凭据不跟随跨域重定向。

bundle Python/uv绝对路径启动，清理PYTHONHOME/PYTHONPATH和继承的token环境；管理token不传引擎/uv/download。普通UI不能保存任意engine_python路径，现有本机环境仅用显式开发模式 TFM_ALLOW_EXTERNAL_ENGINE=1。安装包固定Python3.12.9和uv0.9.5，记录官方来源与摘要；实际签名/公证标注，测试DMG不能宣称通过Gatekeeper。

## 桌面审查补充
正式App使用受限 WKScriptMessageHandlerWithReply `bootstrap`，仅主frame、精确管理origin可获得运行期token；Web ES module闭包保存，不进入URL/DOM/storage。fragment bootstrap只用于明确开发模式浏览器测试，立即删除且不持久化。
握手增加protocol=1、event=ready、port、pid、instance_id、bootstrap_nonce；stdout只该行，其余stderr。Swift30秒期限验证pid/nonce，再认证读取state并核对instance_id。后台接收 --parent-pipe EOF进行退出。
Python放Contents/Frameworks/PythonRuntime，uv在Contents/Helpers；初次运行将自包含Python复制至App专属runtime指纹目录，venv基于此稳定路径而非App包路径，App改名/升级不破坏旧槽。无预创建venv打入DMG；uv禁止自行下载解释器。Python3.12.9/uv0.9.5来源指纹记录。
选择独立升级路径：未来Developer ID签名时仅Python helper允许disable-library-validation以加载可信固定版本MLX扩展，主App不放宽。首轮ad hoc测试包准确披露。逐一签bundle原生代码，再主App、DMG，--deep只验证。
新增POST /api/admin/shutdown；Swift .terminateLater等待Python退出。引擎由supervisor子进程执行，主管理异常死亡通过管道EOF触发supervisor清理自己的Popen进程组；不从持久PID自动杀服务。


## 用户新增内存与外部服务要求（2026-09-29，替代初版外部服务禁止控制条款）

优先复用当前用户已运行且模型 / 配置 / API 身份可验证的 TensorFold 服务。不能兼容时，界面列出具体服务和目标模型，经明确停止后切换确认串行处理。外部控制只使用 macOS audit token 绑定的进程实例信号，绝不以裸 PID 或端口发信号。服务器保存 30 秒一次性确认快照，UID、可执行文件、argv 摘要、模型健康、监听端点和 OS 实例身份均在信号前重核验；不将 token 或完整 argv 返回 UI。

仅一次 SIGTERM。原实例退出、原端点消失、系统压力正常且新模型预算准入成立后才启动目标。120 秒未释放则失败；不自动强杀，也不停止 launchd 重新拉起的替代实例。拿不到实例绑定能力时控制不可用并解释原因。

同数据目录管理进程互斥；全局重任务租约覆盖推理 / 切换 / 升级 / 量化。manager、supervisor、真实重任务子进程继承同一锁描述符，只关闭各自描述符，不显式解锁。主管理进程崩溃时监督器负责清理自有子进程；子进程尚未退出时租约仍禁止第二个重任务。内存预算覆盖模型权重、结构对应缓存、配置上下文和并发、缓存上限及 drafter；架构或采集不明则禁止加载。
