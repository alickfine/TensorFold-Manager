// Fixed interface copy only. Model identifiers, paths, logs and user text are never catalog keys.
const entries = `
由 Manager 管理	Managed by Manager
外部只读接入	External read-only attachment
尚未启动	Not started
基准测试只对当前就绪模型发起请求，不会停止或卸载其他模型。	Benchmark requests target only the current ready model and do not stop or unload other models.
待重启生效：当前服务仍使用已生效配置。	Pending restart: the current service still uses the effective configuration.
聊天工作区	Chat workspace
对话列表	Conversations
生成设置	Generation settings
关闭生成设置	Close generation settings
搜索模型	Search models
新对话	New conversation
搜索对话	Search conversations
暂无对话	No conversations
重命名	Rename
重命名对话	Rename conversation
对话保存在本机；工具调用仅展示，不会由 App 执行。	Conversations stay on this Mac. Tool calls are displayed but not executed by the App.
复制	Copy
复制代码	Copy code
已复制	Copied
请先停止当前生成	Stop the current generation first
对话已切换，请重新发送	Conversation changed; please send again
没有可重试的消息	No message can be retried
活动	Activity
设置	Settings
运行与目录	Runtime & Directories
存储与缓存	Storage & Cache
API 与密钥	API & Keys
查看运行日志与真实基准结果。	View runtime logs and real benchmark results.
按任务集中查看状态和修改配置。	View status and change settings by task.
服务状态与本机用量。	Service status and local usage.
请求明细	Request Details
运行诊断与外部服务	Diagnostics & External Services
运行细节	Runtime Details
推理服务 · {state}	Inference Service · {state}
启动模型	Launch Model
留空时 Hugging Face 默认 main，ModelScope 默认 master；后者可能记录为逐文件提交组成的“文件树快照”，不冒充仓库提交。	When blank, Hugging Face defaults to main and ModelScope defaults to master. The latter may be recorded as a file tree snapshot composed of per-file commits and is never presented as a repository commit.
Hugging Face：{hf}；ModelScope：{modelscope}。第三方镜像永不发送 App 凭据。	Hugging Face: {hf}; ModelScope: {modelscope}. App credentials are never sent to third-party mirrors.
应用目标：{model}。配置档没有模型元数据时不会猜测来源。	Target model: {model}. A profile without model metadata never guesses its source.
采集信息不足，禁止加载新模型：{missing}	Insufficient measurements; loading a new model is blocked: {missing}
确认快照剩余 {seconds} 秒	Confirmation snapshot expires in {seconds} seconds
确认后上传到{existing}{visibility}仓库。	Confirm to upload to the {existing} {visibility} repository.
已存在 · {visibility}	Exists · {visibility}
测试 {id}	Test {id}
应用筛选	Apply Filters
查询	Search
尚无参考测试结果	No Reference Test Results
暂无真实基准结果	No Benchmark Results
暂无任务	No Jobs
暂无日志	No Logs
引擎支持的目标格式	Engine-supported Target Format
暂无工具任务	No Tool Jobs
另有 {count} 个已扫描模型未通过 TensorFold 支持目录门禁，已从启动候选中排除。	{count} additional scanned models failed the TensorFold support allowlist and were excluded from launch candidates.
停止后切换	Stop and Switch
{name} 超出范围	{name} is out of range
请求失败（HTTP {status}）	Request failed (HTTP {status})
界面语言	Interface Language
任务操作已提交：{verb}	Job action submitted: {verb}
确认新建公开仓库 {repo} 并公开发布预览中的 {count} 个文件？	Create public repository {repo} and publicly publish the {count} previewed files?
确认上传预览中的 {count} 个文件到 {repo}（实际可见性：{visibility}）？	Upload the {count} previewed files to {repo} (actual visibility: {visibility})?
停止所选已识别服务，等待端点和内存释放，再启动目标模型 {model}？确认快照最多有效 30 秒；超时不会强杀。	Stop the selected recognized service, wait for its endpoint and memory to be released, then start target model {model}? The confirmation snapshot is valid for at most 30 seconds; timeouts do not force termination.
刷新失败：{message}	Refresh failed: {message}
API 与集成	API & Integrations
API 网关	API Gateway
API 网关端口	API Gateway Port
App 自有生命周期由 Manager 管理；外部兼容只读接入；控制外部服务必须走已验证确认切换。	Manager controls its own processes. Compatible external services are attached read-only; external control requires a verified, confirmed switch.
CLI 兼容预检	CLI Compatibility Check
CSV 已保存	CSV saved
CUDA-only；TensorFold MLX 后端明确不支持。	CUDA only; unsupported by the TensorFold MLX backend.
HF 镜像（第三方）	HF Mirror (Third Party)
Hugging Face 上传	Hugging Face Upload
Hugging Face 下载	Hugging Face Download
Manager 版本	Manager Version
ModelScope 下载	ModelScope Download
OpenAI API 中报告的安全模型标识	Safe model identifier reported through the OpenAI API
OpenAI 兼容网关使用单独签发的 API Key。管理令牌不会显示或复制。	The OpenAI-compatible gateway uses separately issued API keys. The management token is never displayed or copied.
Revision（可留空）	Revision (Optional)
SSE 流式输出	SSE Streaming
Seed（留空随机）	Seed (Blank for Random)
Snapshot 根	Snapshot Root
Tools JSON（可选）	Tools JSON (Optional)
auto、none、已安装仓库 ID 或绝对本地路径	auto, none, an installed repository ID or an absolute local path
group size 无效	Invalid group size
macOS 实际采样；不使用进程 RSS 估算	Measured by macOS; not estimated from process RSS
oMLX 专属内核与缓存	oMLX-specific Kernels & Caches
seed 必须为非负整数	Seed must be a nonnegative integer
上一版本	Previous Version
上下文	Context
上下文长度	Context Length
上传	Upload
上传不可用	Upload unavailable
上传任务已创建	Upload job created
上传确认预览	Upload Confirmation Preview
上传预览已准备；尚未上传	Upload preview ready; no files uploaded yet
上传预览已失效，请重新准备	Upload preview expired. Prepare it again.
上次检查	Last Checked
上游 health 实际采样	Measured from upstream health
下载任务	Download Jobs
下载任务已创建	Download job created
下载时解析并验证不可变文件身份	Immutable file identities are resolved and verified during download
不一致	Mismatch
不可清理原因	Cleanup Unavailable Reason
不可用	Unavailable
不支持的 tool_choice	Unsupported tool_choice
不映射为 TensorFold 成功状态	Not mapped to TensorFold success
为已安装模型保存运行参数与配置档。	Save runtime parameters and profiles for installed models.
主机	Host
主机内存	System Memory
仅 affine；开始前重新执行资源与服务门禁。	Affine only. Resource and service checks run again before starting.
仅交给系统凭据助手；页面不会回填或持久化明文	Sent only to the system credential helper; plaintext is never restored or persisted by the page
仅在后端明确报告时开放	Available only when explicitly reported by the backend
仅强制停止 TensorFold Manager 当前持有的自有引擎进程？此操作不会按 PID 或端口定位其他服务。	Force stop only the engine currently owned by TensorFold Manager? This action does not locate other services by PID or port.
仅显式开发模式可更改	Editable only in explicit developer mode
从服务状态到每次生成，查看本机推理工作台的真实状态。	Inspect actual local inference status, from service health to individual generations.
仓库	Repository
仓库 / 路径	Repository / Path
仓库 ID	Repository ID
仓库必须是精确的 owner/model 标识	Repository must be an exact owner/model identifier
仓库提交	Repository Commit
任务	Tasks
任务状态	Job Status
任务类型	Job Type
你	You
使用 App 中已配置的官方来源凭据	Use the official-provider credentials configured in the App
使用你提供的题目和参考答案验证真实模型输出。	Check actual model responses against your questions and reference answers.
保存	Save
保存当前配置为档案	Save Current Configuration as a Profile
保存服务器设置	Save Server Settings
保存模型级运行参数；运行中的实例需重启后应用。	Save model runtime parameters. A running instance must restart to apply them.
保存模型配置	Save Model Configuration
保存配置	Save Configuration
保存高级配置	Save Advanced Configuration
候选 API 验证	Candidate API Check
候选安装任务已创建	Candidate installation job created
候选安装在隔离环境，验证通过后才可激活；失败保留旧环境。	Candidates install in isolated environments and can activate only after validation. Failures preserve the old environment.
候选激活流程已提交	Candidate activation submitted
候选版本	Candidate Version
停止 TensorFold 推理服务？在途请求将按后端排空策略处理。	Stop the TensorFold inference service? In-flight requests will follow the backend drain policy.
停止会中断当前请求；历史、思考和工具调用保留在本机。	Stopping interrupts the current request. History, reasoning and tool calls remain local.
停止后切换任务已创建	Stop-and-switch job created
停止服务	Stop Service
停止生成	Stop Generation
停止请求处理中	Stop Request in Progress
停用	Disable
健康	Health
健康采样错误	Health Sampling Error
允许启动	Startup Allowed
允许清理	Cleanup Allowed
先取消正在执行的参考测试	Cancel the running reference test first
先断开后切换	Disconnect Before Switching
全部	All
全部模型	All Models
公开	Public
关闭	Off
兼容性	Compatibility
兼容性预检通过；这是 CLI 兼容性证据，尚未加载模型	Compatibility preflight passed. This is CLI compatibility evidence; the model has not been loaded.
内存与服务准入	Memory & Service Admission
内存与服务检查未通过	Memory & Service Checks Failed
内存压力	Memory Pressure
内置聊天	Chat
准入结果	Admission Result
准备上传预览	Prepare Upload Preview
准备步骤会读取远端实际可见性并计算文件列表和摘要；此时不会上传。	Preparation checks actual remote visibility and computes the file list and hashes. No upload occurs at this stage.
凭据	Credentials
凭据已交给系统凭据助手；页面只保留已配置状态	Credentials sent to the system helper; the page retains only the configured status
凭据已删除	Credentials deleted
切换	Switch
创建下载任务	Create Download Job
创建时间	Created At
创建有固定来源、revision 和受管目标目录的可恢复任务。	Create resumable jobs with a fixed source, revision and managed destination.
创建量化任务	Create Quantization Job
删除	Delete
删除这个 App 凭据？后续对应来源任务将不能使用认证访问。	Delete this App credential? Future jobs for this provider will lose authenticated access.
删除这个参考测试题目？已有结果保留。	Delete this reference question? Existing results will be retained.
删除这个配置档？	Delete this profile?
到期时间	Expires At
刷新	Refresh
刷新任务	Refresh Jobs
刷新结果	Refresh Results
功能	Feature
功能适配表	Capability Map
动态能力	Runtime Capabilities
包含参考文本	Contains Reference Text
匹配规则	Match Rule
历史 swap 用量；不等同于当前内存压力	Historical swap usage; not equivalent to current memory pressure
原因	Reason
原生认证握手返回无效	Invalid native authentication handshake
参数	Parameters
参数与进度	Parameters & Progress
参考文本	Reference Text
参考测试队列已创建	Reference test queue created
参考答案	Reference Answer
参考答案测试	Reference-answer Tests
参考题目已添加	Reference question added
发送	Send
取消	Cancel
取消任务并保留可续传文件？	Cancel this job and retain resumable files?
受支持	Supported
受管快照根	Managed Snapshot Root
受管快照目录	Managed Snapshot Directory
受管模型	Managed Model
受管缓存清理	Managed Cache Cleanup
只允许后端固定的官方版本	Only official versions pinned by the backend are allowed
只发送 function 声明；App 不执行工具	Only function declarations are sent; the App does not execute tools
只展示后端运行时实际报告的能力，不从页面静态推断支持。	Only capabilities actually reported by the runtime are displayed; support is not inferred from the interface.
只展示并清理 Manager 拥有且有 manifest 的快照。	Only snapshots owned by Manager with a manifest can be displayed and cleaned.
可分配上限	Allocation Limit
可回收 / 可用内存	Reclaimable / Available Memory
可执行文件	Executable
可用	Available
各模型累计	Per-model Totals
各模型缓存统计	Per-model Cache Statistics
名称	Name
后端固定版本	Backend-pinned Version
后端尚未报告任何能力。	The backend has not reported any capabilities yet.
后端未允许控制此服务	The backend does not permit control of this service
后端未允许清理	Cleanup is not permitted by the backend
后端确认归属	Backend-verified Ownership
后端统一脱敏后展示，支持等级与正文筛选。	Backend-redacted logs with level and text filters.
后端聚合口径	Backend Aggregation Scope
否	No
启动	Start
启动前由已安装引擎 CLI 验证；缺少对应参数时后端会阻止启动并返回原因。	Validated by the installed engine CLI before startup. Missing parameters block startup with a reason.
启动前重新采样并预留系统内存。兼容服务优先复用；切换时先释放旧模型，再核验端点退出和新模型预算。重任务串行执行。	Memory is sampled again before startup with a system reserve. Compatible services are reused first. Switching releases the old model, verifies endpoint exit and checks the new model budget. Heavy tasks run serially.
启动时间	Started At
启动服务	Start Service
启用	Enable
回退	Roll Back
回退到上一个已验证版本？	Roll back to the previous verified version?
回退流程已提交	Rollback submitted
图片 / 视频 / 音频	Image / Video / Audio
图片输入	Image Input
基准任务已提交	Benchmark job submitted
基准测试	Benchmark
填入	Use
填写 auto 或 1–128 的整数	Enter auto or an integer from 1 to 128
外部 Engine Python	External Engine Python
外部推理服务切换	External Inference Service Switch
外部服务仅提供只读用量与请求统计；Manager 不扫描或清理该服务的缓存目录。	External services provide read-only usage and request statistics. Manager does not scan or clean their cache directories.
多模型热加载	Multiple-model Hot Loading
大小	Size
字段数	Field Count
安全边界固定为 App 拥有的快照根	The security boundary is fixed to the App-owned snapshot root
安装任务进行中	Installation in Progress
安装候选	Install Candidate
安装官方引擎	Install Official Engine
安装引擎 →	Install Engine →
安装时间	Installed At
安装模型工具	Install Model Tools
完全相等	Exact Match
完成题数	Completed Questions
官方引擎安装任务已创建	Official engine installation job created
官方版本说明	Official Release Notes
实例 ID	Instance ID
实例未采集	Instance unavailable
实际包版本	Actual Package Version
实际可见性	Actual Visibility
实际输出	Actual Output
密钥已创建，只展示这一次	Key created; shown only once
密钥已撤销	Key revoked
密钥状态已更新	Key status updated
对话已导出	Conversation exported
导入配置档	Import Profile
导出	Export
导出 CSV	Export CSV
导出 JSON	Export JSON
导出日志	Export Logs
尚不存在	Does Not Exist Yet
尚无题目，请先添加参考测试。	No questions yet. Add a reference test first.
工具 JSON 无效	Invalid tools JSON
工具参数过长	Tool arguments are too long
工具必须是标准 function 声明数组	Tools must be an array of standard function declarations
工具运行时	Tools Runtime
工具运行时隔离安装；上传必须先读取远端实际可见性并生成文件预览。	Tools install in an isolated runtime. Uploads require remote visibility checks and a file preview first.
工具选择	Tool Choice
已安装	Installed
已完成题的一致性	Agreement on Completed Questions
已扫描目录	Scanned Directories
已接入	Attached
已提交停止请求	Stop request submitted
已提交启动请求	Start request submitted
已提交重启请求	Restart request submitted
已断开只读外部服务连接；外部进程继续运行	Read-only external service disconnected; its process continues running
已新建对话	New conversation created
已用交换空间	Swap Used
已签发密钥	Issued Keys
已识别服务	Recognized Services
已配置	Configured
平台	Platform
平均 Decode	Average Decode
平均 Prefill	Average Prefill
平均 TTFT	Average TTFT
平均总耗时	Average Total Latency
平均耗时	Average Latency
并发数	Concurrency
应用凭据	Apply Credentials
应用到当前模型	Apply to Current Model
开始测试	Start Test
引擎 PID	Engine PID
引擎内存	Engine Memory
引擎内存与缓存	Engine Memory & Cache
引擎参数	Engine Parameters
引擎尚未就绪	Engine Not Ready
引擎更新	Engine Updates
引擎版本	Engine Version
引擎状态	Engine State
引擎端口	Engine Port
强制停止自有服务	Force Stop Owned Service
归属	Ownership
当前只支持 affine 量化	Only affine quantization is currently supported
当前外部服务只读接入	External service attached read-only
当前模型正在运行	The current model is running
当前模型没有已验证的可用目标格式。	No verified target formats are available for this model.
当前版本	Current Version
当前缓存配置	Current Cache Configuration
当前运行时未报告支持	Support not reported by the current runtime
待应用配置	Pending Configuration
总占用	Total Footprint
总大小	Total Size
总耗时	Total Latency
成功 / 失败 / 取消	Success / Failure / Cancelled
执行队列	Execution Queue
扫描只读；下载目录由后端验证写入范围。	Scanning is read-only. The backend validates download write scope.
扫描配置目录并按运行时白名单展示兼容性，不猜测模型支持。	Scan configured directories and report compatibility using the runtime allowlist, without guessing model support.
指标来源	Metric Source
指标样本	Metric Samples
排空请求并激活已验证的候选版本？	Drain requests and activate the verified candidate?
接受 {name,config} 或本页面导出的 {schema,profile}；未知字段会拒绝。	Accepts {name,config} or {schema,profile} exported by this page. Unknown fields are rejected.
控制	Control
控制仅使用 30 秒一次性进程实例快照。确认后先停止原实例，等待端点与内存释放，再启动目标；超时不会强杀。	Control uses a single-use process snapshot valid for 30 seconds. After confirmation, the original instance stops; endpoints and memory must be released before starting the target. Timeouts do not force termination.
推理 API Key 仅在创建时展示一次；服务端只持久化哈希。	Inference API keys are shown once at creation. Only their hashes are persisted by the server.
推理参数	Inference Parameters
推理框架配置	Engine Configuration
推理流返回错误	Inference stream returned an error
提交真实推理任务并记录运行时、模型、tokens 与耗时。	Run actual inference and record the runtime, model, tokens and latency.
提示词	Prompt
提示词或工具声明过长	Prompt or tool declarations are too long
搜索	Search
撤销	Revoke
撤销这个 API Key？现有客户端将立即无法继续使用。	Revoke this API key? Existing clients will immediately lose access.
操作	Actions
支持	Supported
文件	File
文件数	File Count
文件数量	File Count
文件树快照	File-tree Snapshot
断开连接	Disconnect
新建	New
新建下载	New Download
新建公开仓库：确认后会把所列文件公开发布。	New public repository: confirmation will publish the listed files publicly.
新建对话	New Conversation
新建推理密钥	New Inference Key
新建测试	New Test
无可配置模型	No Configurable Models
无效工具调用索引	Invalid tool-call index
时间	Time
时间范围	Time Range
明确边界	Explicit Boundaries
是	Yes
暂停	Pause
暂无数据	No Data
更改默认目录会先请求明确写入范围授权	Changing the default directory requires explicit write-scope authorization first
更新检查完成	Update check completed
更新状态	Update Status
替换	Replace
最后健康采样	Last Health Sample
最大 tokens	Maximum Tokens
最大生成 tokens	Maximum Output Tokens
最新官方版本	Latest Official Version
最近 24 小时	Last 24 Hours
最近 30 天	Last 30 Days
最近 7 天	Last 7 Days
最近使用	Recently Used
最近错误	Recent Errors
有效天数	Validity (Days)
服务器与目录	Server & Directories
服务未返回流式响应	The service did not return a streaming response
服务模型名	Served Model Name
服务返回了非 JSON 响应	The service returned a non-JSON response
未发现可安装候选。	No installable candidates found.
未发现当前用户的 TensorFold / oMLX 推理服务。	No TensorFold / oMLX inference services found for the current user.
未安装	Not Installed
未知	Unknown
未知凭据类型	Unknown credential type
未确认	Unconfirmed
未设置	Not Set
未连接	Disconnected
未选择模型	No Model Selected
未配置	Not Configured
未采集	Unavailable
本机模型	Local Models
条数	Row Limit
来源	Source
来源目录	Source Directory
来自当前引擎的配置兼容预检；转换后仍需核验实际权重。	From the current engine's configuration compatibility preflight. Actual weights still require verification after conversion.
架构	Architecture
标准 MLX 量化	Standard MLX Quantization
校验并导入	Validate & Import
样本数	Sample Count
检查更新	Check for Updates
模型	Model
模型 ID	Model ID
模型下载	Model Download
模型下载器	Model Downloader
模型工具安装任务已创建	Model tools installation job created
模型库	Model Library
模型扫描完成	Model scan completed
模型数量	Model Count
模型权重未完整安装	Model weights are not fully installed
模型目录（每行一个）	Model Directories (One per Line)
模型路径	Model Path
模型配置	Model Configuration
模型配置已保存	Model configuration saved
模型预算为保守估计，并非实测峰值。	Model budgets are conservative estimates, not measured peaks.
没有可启动的受支持目标模型	No supported target models available to start
没有需要停止后切换的已识别服务。	No recognized services require stopping before a switch.
活动 commit	Active Commit
活动版本	Active Version
流式响应包含无效 JSON	Streaming response contains invalid JSON
流式响应在完成标记前中断，已保留收到的部分内容	The stream ended before its completion marker. Received partial content was retained.
测试题目	Test Question
添加测试	Add Test
添加题目	Add Question
清理受管快照	Clean Managed Snapshots
清理只作用于后端确认归属的快照，并要求引擎已停止。模型权重与外部目录不会被删除。	Cleanup applies only to ownership-verified snapshots and requires a stopped engine. Model weights and external directories are not deleted.
清理后端确认归属的受管快照？	Clean the managed snapshots whose ownership was verified by the backend?
清理缓存	Clean Cache
清空全部参考测试结果？题目保留。	Clear all reference test results? Questions will be retained.
清空结果	Clear Results
源模型	Source Model
激活候选	Activate Candidate
版本	Version
版本与更新	Versions & Updates
版本与管理实例	Versions & Management Instance
版本未采集	Version Unavailable
物理内存	Physical Memory
状态	Status
现有	Existing
生成上限	Generation Limit
生成密钥	Generate Key
生成已取消。	Generation cancelled.
生成设置已应用	Generation settings applied
留空时由后端使用安全名称；输出固定在 App 受管目录	Leave blank for a safe backend-generated name. Outputs are restricted to the App-managed directory.
监听端口	Listening Port
目录暂无条目；可手动输入经过核验的仓库。	No catalog entries yet. You can enter a verified repository manually.
目标仓库	Target Repository
目标模型	Target Model
目标目录	Destination Directory
真实结果	Actual Results
确认上传	Confirm Upload
确认快照不可用，请刷新	Confirmation snapshot unavailable. Refresh and try again.
确认新建公开仓库并上传	Confirm Public Repository Creation & Upload
私有	Private
秒	Seconds
端口	Port
端口与目录	Ports & Directories
端口与配置	Ports & Configuration
端点	Endpoints
第三方镜像不能接收 App 凭据	Third-party mirrors cannot receive App credentials
等级	Level
筛选	Filter
筛选真实网关请求记录；未采集字段保持“未采集”。	Filter actual gateway request records. Missing metrics remain unavailable.
管理实例	Management Instance
管理服务	Management Service
管理监听端口与受管目录；保存不会接管已占用端口。	Manage listening ports and managed directories. Saving does not take over occupied ports.
类型	Type
精确 owner/model	Exact owner/model
系统采集	System Measurements
系统预留	System Reserve
累计请求	Total Requests
结果	Results
结果历史	Result History
结果已清空	Results cleared
统计与用量	Statistics & Usage
继续	Resume
缓存	Cache
缓存 tokens	Cached Tokens
缓存清理完成	Cache cleanup completed
缓存管理	Cache
编辑持久化默认值；页面只提交协议允许的字段。	Edit persisted defaults. Only fields allowed by the protocol are submitted.
缺失信息	Missing Information
网关实际记录	Actual Gateway Records
网关默认仅监听 loopback。客户端密钥请在“认证与密钥”创建。	The gateway listens on loopback by default. Create client keys under Authentication & Keys.
能力	Capabilities
能力尚未准备完成	Capability Not Ready
脱敏日志	Redacted Logs
脱敏日志已导出	Redacted logs exported
自有服务强制停止请求已提交	Force-stop request submitted for the owned service
认证与密钥	Authentication & Keys
设为默认	Set as Default
设置已保存	Settings saved
评分为参考答案一致性：完全相等或包含参考文本，不代表模型的通用知识准确率。temperature 固定为 0；思考关闭。	Scores measure reference-answer agreement: exact match or reference-text inclusion. They do not represent general model accuracy. Temperature is fixed at 0; thinking is off.
请先停止推理服务	Stop the inference service first
请先启动并等待引擎就绪	Start the engine and wait until it is ready
请先安装 TensorFold 引擎	Install the TensorFold engine first
请先安装并选择受支持模型	Install and select a supported model first
请先扫描或下载受支持模型。	Scan or download supported models first.
请先明确选择配置档的应用目标模型	Select the target model for this profile first
请先添加参考测试	Add a reference test first
请先等待推理服务就绪	Wait until the inference service is ready
请先选择模型	Select a model first
请在总览断开外部服务，或使用已确认的停止后切换	Disconnect the external service in Overview, or use a confirmed stop-and-switch
请求	Requests
请求参数	Request Parameters
请求可见性	Requested Visibility
请求数	Request Count
请求记录	Request Records
请立即保存 API Key	Save Your API Key Now
请输入凭据	Enter credentials
请选择仍在有效期内的服务快照和目标模型	Select an unexpired service snapshot and a target model
请选择仓库可见性	Select repository visibility
路径	Path
身份类型	Identity Type
轮次	Turns
输入 tokens	Input Tokens
输入消息	Enter a message
输入真实测试提示词	Enter an actual test prompt
输出	Output
输出 tokens	Output Tokens
输出名称	Output Name
运行中	Running
运行全部	Run All
运行总览	Overview
运行日志	Logs
运行时版本	Runtime Version
运行时目录	Runtime Directory
运行时能力	Runtime Capabilities
运行模型	Running Model
运行次数	Run Count
运行环境	Runtime Environment
运行队列	Run Queue
进度	Progress
进程 PID	Process PID
进程边界	Process Boundaries
远端现状	Remote State
连接失败	Connection Failed
通过	Passed
通过受认证的管理代理调用当前 TensorFold，并保存本地历史。	Call the current TensorFold engine through the authenticated management proxy and save local history.
通过题数	Passed Questions
部分结果	Partial Results
配置	Configuration
配置接口只返回 configured 状态；密码输入不会写入页面状态或本地存储。	Configuration APIs return only configured status. Password inputs are not written to page state or local storage.
配置档	Profiles
配置档 JSON	Profile JSON
配置档 JSON 格式无效	Invalid profile JSON
配置档不存在	Profile not found
配置档已保存	Profile saved
配置档已删除	Profile deleted
配置档已导入	Profile imported
配置档已导出	Profile exported
配置档已应用；运行中参数等待重启生效	Profile applied; running parameters take effect after restart
配置档缺少名称	Profile name missing
重启	Restart
重新扫描	Rescan
重试	Retry
量化	Quantize
量化不可用	Quantization unavailable
量化与上传	Quantization & Upload
量化任务已创建	Quantization job created
量化位宽无效	Invalid quantization bit width
量化模式	Quantization Mode
错误	Error
阻断原因	Block Reason
音频输入	Audio Input
预估需求	Estimated Requirement
题目	Questions
题目已删除	Question deleted
验证兼容性	Check Compatibility
高级参数	Advanced Parameters
默认模型字段	Default Model Fields
默认模型已保存	Default model saved
（官方来源，可选 App 凭据）	(Official source; optional App credentials)
（第三方，不发送凭据）	(Third party; credentials are not sent)
主导航	Main Navigation
运行	Runtime
服务	Services
工具	Tools
工作台	Workspace
工作台 / {page}	Workspace / {page}
实例 {id}	Instance {id}
管理界面在线 · 推理服务 {state}	Manager online · Inference service {state}
更新于 {time}	Updated at {time}
正在连接管理服务	Connecting to management service
App 版本未采集	App version unavailable
正在建立安全连接…	Establishing a secure connection…
管理服务连接中	Connecting to management service
关闭	Close
无法连接管理服务	Cannot Connect to Management Service
请从 TensorFold Manager App 启动页面。浏览器开发测试需要显式 loopback dev 模式。	Open this page from TensorFold Manager. Browser testing requires explicit loopback development mode.
开始一段真实本机对话	Start a real local conversation
思考过程	Reasoning
工具调用（仅展示，未执行）	Tool Calls (Displayed Only; Not Executed)
浏览器耗时	Browser Latency
消息	Message
生成设置	Generation Settings
应用生成设置	Apply Generation Settings
已安装工具版本	Installed Tools Version
API 端点	API Endpoints
`
.trim().split('\n').map(line => line.split('\t'));
const extraEntries = [
  ['正在思考…\n', 'Thinking…\n'],
  ['请先选择已通过当前引擎检测的模型', 'Select a model verified by the current engine'],
  ['另有 {count} 个已安装模型尚未通过当前引擎的离线启动检测，已从启动候选中排除。', '{count} installed model(s) have not passed the current engine offline launch check and are excluded from launch choices.'],
  ['目录支持', 'Catalog Supported'],
  ['尚未通过当前引擎检测', 'Not yet verified by the current engine'],
  ['可启动', 'Launchable'],
  ['默认', 'Default'],
  ['选择 TensorFold 已确认支持的模型，并从对应官方模型库直接下载。', 'Choose a model confirmed by TensorFold and download it directly from its listed model source.'],
  ['受支持模型与来源', 'Supported Model and Source'],
  ['暂无可下载的受支持模型', 'No supported model is available to download'],
  ['仓库、版本与受管目录由后端支持目录确定', 'Repository, revision, and managed directory come from the backend support catalog'],
  ['开始下载', 'Start Download'],
  ['支持目录', 'Support Catalog'],
  ['由模型库解析', 'Resolved by Model Source'],
  ['HF 镜像', 'HF Mirror'],
  ['保存模型级生成与推测解码参数；运行中的实例需重启后应用。', 'Save model generation and speculative decoding parameters. Restart a running instance to apply them.'],
  ['只管理服务级资源参数；模型生成与推测解码参数在模型库的配置弹窗中编辑。', 'Manage service resource parameters here. Edit model generation and speculative decoding settings from the Model Library dialog.'],
  ['运行时', 'Runtime'],
  ['TensorFold 版本', 'TensorFold Version'],
  ['运行状态', 'Runtime State'],
  ['服务资源', 'Service Resources'],
  ['保存框架配置', 'Save Engine Settings'],
  ['查看运行环境与模型目录，并由后端任务扫描本机磁盘。', 'View the runtime and model directories, and let a backend job scan this Mac.'],
  ['扫描整台 Mac', 'Scan This Mac'],
  ['模型扫描正在进行', 'A model scan is running'],
  ['模型目录', 'Model Directories'],
  ['目录扫描只读；全盘扫描找到模型后由后端追加目录并重新扫描。', 'Directory scanning is read only. The backend adds directories found by the full scan and rescans models.'],
  ['保存目录', 'Save Directories'],
  ['全盘扫描任务', 'Full Scan Jobs'],
  ['尚未运行全盘模型扫描', 'No full model scan has run yet'],
  ['扫描目录', 'Scanned Directories'],
  ['发现模型', 'Models Found'],
  ['阶段', 'Phase'],
  ['新增目录', 'Added Directories'],
  ['跳过', 'Skipped'],
  ['部分结果', 'Partial Result'],
  ['扫描限制', 'Scan Limits'],
  ['扫描达到安全限制，当前结果不表示整盘扫描完成。', 'The scan reached its safety limit. These results do not mean the entire disk was scanned.'],
  ['扫描检查上限为 180 秒；已登记模型目录总数最多 32 个。触发安全限制时会标为部分结果。', 'The scan checks a 180-second limit, and registered model directories are capped at 32 total. Results are marked partial when a safety limit is reached.'],
  ['集中管理端口、OpenAI 兼容端点与独立 API Key。管理令牌不会显示或复制。', 'Manage ports, OpenAI compatible endpoints, and separate API keys together. The management token is never shown or copied.'],
  ['网关默认仅监听 loopback。客户端密钥在本页创建。', 'The gateway listens on loopback by default. Create client keys on this page.'],
  ['网关配置状态', 'Gateway Configuration Status'],
  ['网关错误', 'Gateway Error'],
  ['待重启应用', 'Pending Restart'],
  ['已监听', 'Listening'],
  ['未监听', 'Not Listening'],
  ['已保存端口将在 Manager 重启后绑定；当前 Base URL 仍使用实际监听端口。', 'The saved port will bind after Manager restarts. The current Base URL still uses the actually listening port.'],
  ['端口参数', 'Port Settings'],
  ['保存端口', 'Save Ports'],
  ['升级会保留当前可用环境，并展示后端返回的真实阶段、失败证据与可用动作。', 'Upgrades preserve the current working environment and show real backend phases, failure evidence, and available actions.'],
  ['升级引擎', 'Upgrade Engine'],
  ['安装引擎', 'Install Engine'],
  ['更新任务正在进行', 'An update job is running'],
  ['候选状态', 'Candidate Status'],
  ['阻碍', 'Blockers'],
  ['后端未允许激活', 'Activation is not allowed by the backend'],
  ['后端未允许升级', 'Upgrade is not allowed by the backend'],
  ['安装任务证据', 'Install Job Evidence'],
  ['升级任务证据', 'Upgrade Job Evidence'],
  ['激活任务证据', 'Activation Job Evidence'],
  ['后端尚未报告任务证据', 'The backend has not reported job evidence'],
  ['后端统一脱敏后展示。', 'Logs are displayed after backend redaction.'],
  ['筛选', 'Filter'],
  ['选择测试档位，对当前就绪模型运行真实推理并查看结果。', 'Choose a test tier, run real inference on the current ready model, and review the results.'],
  ['运行测试', 'Run Benchmark'],
  ['测试档位', 'Test Tier'],
  ['快速', 'Quick'],
  ['标准', 'Standard'],
  ['深入', 'Thorough'],
  ['提示词（留空使用档位预设）', 'Prompt (leave blank for the tier preset)'],
  ['输入自定义测试提示词', 'Enter a custom benchmark prompt'],
  ['最大生成 tokens（留空使用预设）', 'Maximum generation tokens (leave blank for preset)'],
  ['运行次数（留空使用预设）', 'Runs (leave blank for preset)'],
  ['请选择有效的测试档位', 'Choose a valid benchmark tier'],
  ['基准测试参数无效', 'Invalid benchmark parameters'],
  ['已完成', 'Completed'],
  ['查看逐轮结果与参数', 'View Per-run Results and Parameters'],
  ['通过当前 TensorFold 服务进行真实流式对话。', 'Use the current TensorFold service for a real streaming conversation.'],
  ['当前模型', 'Current Model'],
  ['切换模型', 'Switch Model'],
  ['清空', 'Clear'],
  ['生成参数', 'Generation Parameters'],
  ['Enter 发送 · Shift+Enter 换行', 'Enter to send · Shift+Enter for a new line'],
  ['当前生成尚未结束', 'The current generation is still running'],
  ['停止', 'Stop'],
  ['生成', 'Generate'],
  ['停止会中断当前请求；当前消息和已生成内容仍保留。', 'Stopping interrupts the current request while keeping the message and generated content.'],
  ['请选择目录中的受支持模型', 'Choose a supported model from the catalog'],
  ['全盘模型扫描任务已创建', 'Full model scan job created'],
  ['引擎升级任务已创建', 'Engine upgrade job created'],
  ['配置档记录的默认模型为：\n{profileModel}\n\n本次明确应用到当前模型：\n{target}\n\n继续吗？', 'The profile default model is:\n{profileModel}\n\nThis operation will explicitly apply it to the current model:\n{target}\n\nContinue?'],
  ['允许 TensorFold Manager 写入这个模型目录？\n{directory}\n\n该授权只用于下载任务，不会删除外部权重。', 'Allow TensorFold Manager to write to this model directory?\n{directory}\n\nThis authorization is used only for download jobs and does not delete external weights.'],
];
export const EN_MESSAGES = Object.freeze(Object.fromEntries([...entries, ...extraEntries]));
