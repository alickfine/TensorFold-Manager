# TensorFold Manager Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development or superpowers:executing-plans task-by-task. 用户明确要求互不冲突的模块并行；使用专属文件所有权和固定协议消除冲突。

**Goal:** 交付可从GitHub下载并安装的macOS arm64 DMG，含真实Web管理与TensorFold推理闭环。

**Architecture:** Swift/AppKit/WKWebView启动App内Python管理层，管理层独立存活并管理自己的TensorFold子进程。原版上游安装到独立venv，动态CLI适配；loopback管理与OpenAI网关分开，SQLite记录持久状态。

**Tech Stack:** Swift 6, WKWebView, Python 3.12 stdlib, HTML/CSS/ES modules, uv isolation, SQLite。

**Spec:** docs/superpowers/specs/2026-09-29-manager-design.md

## Global Constraints
- 名称 TensorFold Manager；macOS Apple Silicon；最终 GitHub Releases DMG。
- 自动检查更新、手动升级、失败回退。
- 按用户最新内存管理要求：兼容服务先复用；不兼容服务仅在新鲜同用户 OS 身份绑定和明确切换确认下停止，等待退出和资源释放。保持 oMLX 配置与既有凭据。
- 正式运行不能包含示例指标/模拟成功；不支持能力禁用并解释。
- 仅loopback默认；管理bearer随机，API key只保存hash；所有外部内容HTML转义。
- 命令参数数组，无shell；用户目录和数据不打包进DMG。

## Review Focus
- 端口被外部服务占用：拒绝启动且不能接管它。
- 保存与加载/就绪不同步：明确pending、starting、ready和failed。
- API并发时停止/更新：排空超时不强行覆盖当前环境。
- 恶意模型名/路径/revision/Origin：参数校验、路径归属、管理认证拒绝。
- 应用退出/升级失败：停止拥有的进程，旧环境可恢复，状态持久化。

## API protocol (all task interfaces)
Management /api/* requires Authorization Bearer runtime admin token, errors {error:{message,code}}, success JSON object.
GET /api/state: {app_version,settings,engine:{state,pid,model,version,health,error,started_at,pending},system,models:[{id,name,repo,path,size_bytes,family,installed,supported}],stats:{total,models,requests},jobs,keys,capabilities,update,profiles}. All optional/uncollected metrics null.
PUT /api/settings { ...editable settings }; persistent selected_model, engine_python, model_dirs[], engine_port, gateway_port, context, max_tokens, temperature, top_p, top_k, parallel, thinking, prompt_cache_gib, mlx_cache_gib, snapshot_dir.
POST /api/engine/start {model}; /stop {force:false}; /restart {model}. Start async returns state, poll /state.
GET /api/models; POST /api/models/scan; PUT /api/models/config {model,config}; GET/POST /api/profiles; DELETE /api/profiles/<id>.
GET /api/logs?level=&query=&limit=; GET /api/stats?model=&range=; GET /api/stats/export CSV.
GET /api/downloads/catalog; POST /api/downloads {repo,source,revision,directory}; POST /api/jobs/<id>/{pause,resume,cancel,retry}; GET /api/jobs.
GET /api/updates; POST /api/updates/check; POST /api/updates/install {version}; POST /api/updates/activate; POST /api/updates/rollback; POST /api/engine/install (bootstrap official pinned upstream into isolated environment).
GET /api/cache; POST /api/cache/clear {confirm:true} owned snapshots only engine stopped.
GET /api/keys; POST /api/keys {name,expires_days} returns plaintext only once; DELETE /api/keys/<id>; POST /api/keys/<id>/toggle.
GET /api/chat/history; POST /api/chat/history {messages}; POST /api/chat/completions proxy with admin token, stream supported; POST /api/benchmark {prompt,max_tokens,runs}; GET /api/benchmark/results.
POST /api/tools/quantize and /api/tools/upload gated tools; GET /api/capabilities.
OpenAI /v1/models,/v1/chat/completions,/v1/completions on gateway port requires issued API key.
Startup Python module tfmanager.server --data-dir PATH --web-dir PATH --port 0 accepts TFM_ADMIN_TOKEN environment. Prints one JSON line {ready:true,port:N}; never prints token. Gateway chosen settings port. Swift 通过 exact-origin/main-frame WebKit bootstrap 返回令牌，JS 仅保存在模块闭包，不写 URL 或 storage。 Shutdown SIGTERM cleans owned engine and gateway.

### Task 1: Python management/backend (independent owned tree)
**Files:** Create manager/tfmanager/{__init__,state,engine,models,downloads,updates,gateway,server,jobs}.py, tests/test_{state,engine,gateway,server,downloads,updates}.py.
**Interfaces:** all protocol above, module `PYTHONPATH=manager python -m tfmanager.server`; no frontend or macOS files.
- [ ] Write failing unittest cases for persistence, key rejection, injection validation, lifecycle/port conflict, readiness and failed-process handling.
- [ ] Implement real process lifecycle, model catalog/scan, settings persistence, authenticated HTTP and OpenAI streaming proxy/statistics.
- [ ] Implement task lifecycle, source adapters/downloads, version bootstrap/check/stage/activate/rollback, profiles/logs/cache/chat/benchmark/tool capability gates.
- [ ] Run unittest discover, HTTP integration with controlled fake engine (test fixture only), record RED/GREEN and limitations.
- [ ] Commit own tree and report. Independent review required before mark complete.

### Task 2: Web management (independent owned tree)
**Files:** Create web/{index.html,app.css,app.js,api.js,views/*.js}, tests/web.test.mjs.
**Interfaces:** API protocol above; reuse approved prototype styling only, no simulation state. Static resources served by Python.
- [ ] Write node tests for escaping, error handling and settings serialization; verify RED.
- [ ] Implement all16 modules, live polling, authenticated requests, real lifecycle/settings/keys/tasks/update forms; null means未采集.
- [ ] Implement streaming chat+abort, persisted history, stats/filter/export, download/catalog/config and gated tool interfaces.
- [ ] Run node tests/syntax, browser acceptance against real backend once integrated; commit own tree, report. Independent review required.

### Task 3: macOS App and DMG (root owned tree)
**Files:** Create macos/{main.swift,Info.plist}, scripts/{build-app.py,release.sh}, tests/test_packaging.py, .github/workflows/release.yml.
**Interfaces:** bundle Resources contains standalone python/bin/python3, manager/, web/ and uv tool. Python readiness contract above. No system Python dependency. Launch uses random token; validate navigation to own loopback only, external links open in normal browser.
- [ ] Write failing layout tests, build and launch fixture smoke contract.
- [ ] Implement native App menus/lifecycle/persisted user data path, Python spawn/readiness/error UI, secure WebKit token bridge and cleanup.
- [ ] Bundle relocatable managed Python3.12 and uv with provenance, compile arm64 app, ad hoc sign if no Developer ID; mark signing status accurately.
- [ ] Build DMG with App and Applications symlink; test mount/bundle/launch/quit/sha and CI tagged release artifacts.

### Task 4: Integration, security review and real acceptance
**Files:** README.md, docs/acceptance.md and targeted fixes by task owners.
- [ ] Review tasks and auth/process/update boundaries on most capable reviewer; fix material findings.
- [ ] Real local model start+readiness+chat API+UI chat+stats+stop/restart/model switch; preserve unrelated services.
- [ ] Source/download/update failure isolation; port conflicts, unauthorized API refusal, restart persistence and App cleanup tests.
- [ ] DMG install/launch and source no credential check; publish public source and versioned Release DMG/SHA256.
- [ ] Record fresh evidence, limitations, signing status and installer link for user acceptance.

## Binding security preflight additions (apply to all tasks)
- Exact Host `127.0.0.1:<actual-port>` only; reject duplicate Host; Origin if present exactly `http://127.0.0.1:<actual-port>`, reject null/cross origin. No CORS wildcard, CSP self only. Token mandatory even without Origin.
- WKWebView same host and exact management port only, HTTP(S) external link in browser; no arbitrary schemes. Parent stdin keepalive: server --parent-pipe watches EOF and shuts down owned processes.
- Popen current handle/process group only; never recovered PID/killall/port kill. Bind conflict cannot be treated as external health readiness. Engine shutdown allows120s graceful cleanup; timeout markedfailed, forcedkill only explicit.
- Upgrade stages/install do not touch active environment. Exclusive lifecycle lock, drain timeout abort, pinned official release/commit only, atomic pointer/config backup, candidate fails => restart old model and prove API readiness. No parallel candidate/old model loads.
- Download roots require explicit write scope; private staging and owned manifests, reject traversal/symlink escape. Cancel retains task files for resume, never deletes external weights. Cache clear only owned manifest snapshot and stopped engine.
- Clean runtime env including PYTHONHOME/PYTHONPATH, admin token stripped from children. Arbitrary engine_python ordinary setting rejected; explicit TFM_ALLOW_EXTERNAL_ENGINE=1 development only. Bundle standalone Python3.12.9, uv0.9.5 provenance/SHA recorded; no claim Gatekeeper if ad hoc.
- Test auth/Host/Origin, conflict/oldPID/AppEOF, traversal/symlink/cancel, failed upgrade true old API recovery, DMG startup without global runtimes, preserve unrelated services unless explicitly confirmed switch.

## Desktop review overrides (supersede earlier fragment/resource wording)
- Native token via `window.webkit.messageHandlers.bootstrap.postMessage({})` Promise returning {token,instance_id}; handler only main frame exact management origin. JS token module closure; no URL/storage. Browser dev fragment bootstrap allowed only explicit dev testing, removed immediately, not persisted.
- Ready JSON {protocol:1,event:'ready',ready:true,port,pid,instance_id,bootstrap_nonce}; TFM_BOOTSTRAP_NONCE environment; stdout readiness only. GET/api/state includes instance_id. Swift30s timeout, childPID/nonce and authenticated instance check before Web load.
- Runtime bundle Contents/Frameworks/PythonRuntime; uv Contents/Helpers/uv. Copy bundled relocatable Python to AppSupport/runtimes/<sha> on first launch. All version venv use this stable copied Python, not bundle path. uv --no-python-downloads enforced. Never pack local venv. Sources/provenance manifests include hash.
- New POST /api/admin/shutdown grace120s; Swift async terminateLater. Engine supervisor with own Popen process group and parent liveness pipe, EOF cleanup prevents manager crash orphan. No persisted PID automatic termination.
- Future hardened runtime Python helper only may disable library validation for independent pinned engine upgrades. Main app no relaxed entitlements. ad hoc test DMG disclosed. Sign individual MachOs then App then DMG; verify each.
- Native export interface: `window.webkit.messageHandlers.exportFile.postMessage({name,content})` returns {saved:true/false}; main frame exact origin only, text<=10MiB, safe filename extension csv/json/txt/md, NSSavePanel user chooses destination. Needed for exports under WKWebView strict navigation; browser fallbackBlob only. No arbitrary silent path writes.
- Packaging correction after real codesign failure: standalone runtime is sealed within `Contents/Frameworks/PythonRuntime.framework/Versions/A/Resources/runtime`, with versioned framework Info.plist/main library, relative Current/Resources links. Swift copies this resource runtime to stable AppSupport. Sign its individual MachOs, framework, then App; native and framework main executables are signed by their enclosing bundles. Apple reference https://developer.apple.com/library/archive/technotes/tn2206/ .

## Approved implementation extensions and fresh review fixes (2026-09-29)
- User selected automatic update checks / manual activation / failure rollback.
- Full reusable management features include isolated standard MLX conversion and HF upload tools, explicit own-provider credential entry in Keychain. Fixed service/account helper, bounded stdin JSON, no existing credentials read; fixtures only for credential operations. Upload prepares exact repository visibility/files/size for user confirmation; no headless real upload.
- User added memory protection: discover existing TensorFold/oMLX services before loading; reuse compatible service, otherwise stop before replacing; no parallel heavyweight loads. Implement real macOS pressure/capacity and conservative model/context/concurrency/cache budget gates, shared heavy-task lease and explicit ownership/identity. Unknown budgets are blockers. Only same-user live CLI identity can support automatic attachment; arbitrary endpoint or model name is insufficient. External lifecycle control requires separate verified live identity contract; no kill-by-port or persisted-PID operations.
- Independent task3 review found startup writes pyc into signed App, runtime fingerprint incompleteness, unbounded quiet quit, uv license/provenance/CI gaps. Fix: native and child Python -B; manifest of all actual signed runtime files/links/modes + signing identity, verify stable copy before use; timeout explains state and offers explicit stop of own Process; package uv licenses; fixed archive checksum; actual build OS; hardened runtime/timestamp for future DeveloperID.
- Native WebKit confirm delegate required for actual stop/update/download-scope actions; main-frame exact origin only with visible native confirmation.
- Fresh local native engine bootstrap v0.3.6.2 commit71377a5373ed7b394f1b480ba2a6a3986b03af1c succeeded. Qwen compatible local variant CLI preflight and real inference returned status200; owned test process exited after App parent EOF. External8089 no longer listening during later readback; no signal was sent to it. No further heavyweight model loads until memory gates are implemented.

## 最终执行记录（2026-09-29，取代早期未勾选的任务状态）

- Task 1 / 2 / 3 已实施：真实管理层、17 页 Web、原生 App、隔离运行时、DMG / GitHub 发布流程。
- Task 4 开发方验收完成：149 Python / 38 Web / 原生检查本机及 GitHub CI 通过；真实模型下载、量化及产物推理、双向模型切换、API 401/200、基准、参考答案、主引擎升级和回退。
- 全局 OS 租约通过重复描述符保持至升级、候选失败恢复及模型切换完成；旧子进程退出与资源重新采样后才加载目标，重任务无空窗。
- 独立审查的两项 P2 已由主线程修复并回归；后续 agent 用量限制已披露。实际转换进一步发现 scales dtype 必须 bfloat16，已修复并验证真实推理。
- 公开 v0.1.0-alpha.1 的 DMG / SHA256 已发布，实际下载、摘要核对、安装、聊天、退出和签名验收通过。完整证据与限制见 docs/acceptance.md。
- 未操作用户既有外部服务、未写入真实 provider token、未真实上传模型。用户安装验收等待反馈，Developer ID / 公证未提供。
