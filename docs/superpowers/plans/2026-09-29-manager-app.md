# TensorFold Manager Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development or superpowers:executing-plans task-by-task. 用户明确要求互不冲突的模块并行；使用专属文件所有权和固定协议消除冲突。

**Goal:** 交付可从GitHub下载并安装的macOS arm64 DMG，含真实Web管理与TensorFold推理闭环。

**Architecture:** Swift/AppKit/WKWebView启动App内Python管理层，管理层独立存活并管理自己的TensorFold子进程。原版上游安装到独立venv，动态CLI适配；loopback管理与OpenAI网关分开，SQLite记录持久状态。

**Tech Stack:** Swift 6, WKWebView, Python 3.12 stdlib, HTML/CSS/ES modules, uv isolation, SQLite。

**Spec:** docs/superpowers/specs/2026-09-29-manager-design.md

## Global Constraints
- 名称 TensorFold Manager；macOS Apple Silicon；最终 GitHub Releases DMG。
- 自动检查更新、手动升级、失败回退。
- 不停止外部引擎、不改oMLX、不读现有凭据；只管理本App创建的子进程。
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
Startup Python module tfmanager.server --data-dir PATH --web-dir PATH --port 0 accepts TFM_ADMIN_TOKEN environment. Prints one JSON line {ready:true,port:N}; never prints token. Gateway chosen settings port. Swift opens URL fragment #token=<token>; JS captures to sessionStorage then removes fragment. Shutdown SIGTERM cleans owned engine and gateway.

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
- [ ] Implement native App menus/lifecycle/persisted user data path, Python spawn/readiness/error UI, secure token fragment and cleanup.
- [ ] Bundle relocatable managed Python3.12 and uv with provenance, compile arm64 app, ad hoc sign if no Developer ID; mark signing status accurately.
- [ ] Build DMG with App and Applications symlink; test mount/bundle/launch/quit/sha and CI tagged release artifacts.

### Task 4: Integration, security review and real acceptance
**Files:** README.md, docs/acceptance.md and targeted fixes by task owners.
- [ ] Review tasks and auth/process/update boundaries on most capable reviewer; fix material findings.
- [ ] Real local model start+readiness+chat API+UI chat+stats+stop/restart/model switch; preserve unrelated services.
- [ ] Source/download/update failure isolation; port conflicts, unauthorized API refusal, restart persistence and App cleanup tests.
- [ ] DMG install/launch and source no credential check; publish public source and versioned Release DMG/SHA256.
- [ ] Record fresh evidence, limitations, signing status and installer link for user acceptance.
