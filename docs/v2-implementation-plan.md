# TensorFold Manager v2 · 实施计划

> 基线：v1.1（dmg 已装 /Applications）· 原型：prototypes/tfm2.html（老板已确认方向）
> 方法论：superpowers —— 任务颗粒小、每个可验证、TDD 先行、只提交已验证的东西

## Grill 定案（2026-10-05，老板确认）

| 决策点 | 结论 |
|---|---|
| 壳层技术路线 | **原生抄 oMLX**：pyobjc NSApplication + WKWebView 主窗 + NSStatusItem 菜单栏。弃 pywebview（无 SystemTray、双窗别扭）。pyobjc 全家桶 venv 和打包运行时里已有，零新增依赖 |
| 引擎语义 | **单实例，加载即切换**。优化：新模型 ready 后才停旧（重叠期内存峰值 ~38G，256G 富余），用户视角零中断；失败则旧实例继续服务 |
| 自动更新 | 检查+提示+一键动作，**全部 GitHub**（实测 PyPI 无此包）。引擎→ashhart/TensorFold releases/latest（现报 v0.6.5），一键 git archive 拉 tag 安装 + 重启；App→本仓库 releases 列表（latest 端点因旧稿只有 prerelease 而 404，需过滤 draft/prerelease），一键打开下载页。不做应用内自替换 |
| 工程基线 | git init + feature/v2 分支；每阶段一提交；打包从已提交修订导出 |
| 旧对话记录 | 清空重开（v1 history.json 归档不删） |

我自己定的实现细节（可否）：端口固定 8080 单实例无需分配；JS 桥用 WKScriptMessageHandler（等价替代 pywebview 的 window.external）；前端渲染库直接拷 oMLX 的 marked/highlight.js/DOMPurify 离线资产；菜单栏面板同样用 WKWebView 装 HTML（视觉与主窗统一）。

---

## 阶段 A · 基线（先能回退，再动手）

### A1 git 基线
- 路径：`tensorfold-manager/` 根
- 做：`git init`；`.gitignore`（`__pycache__/`、`dist/`、`*.pyc`）；`git add` 全部源码；提交 `baseline: v1.1.0`
- **GitHub 关系（查证后修正）**：远端 `alickfine/TensorFold-Manager` 已存在，但其 main 是旧稿目录结构（macos/ manager/ web/ scripts/ tests/，与本地 `tensorfold-manager/` 完全不同源）——**不 pull 不合并**，加 remote 后只 push 新分支 `feature/v2`；main 保持旧稿历史不动
- 验证：`git log --oneline` 有一条；`git status` 干净；`python smoke_test.py` 仍全绿（基线没改坏）

### A2 feature 分支
- `git checkout -b feature/v2`

## 阶段 B · 后端（TDD：每个任务先加失败测试到 smoke_test.py）

### B1 engine.py 参数透传 + 每模型持久化
- 文件：`backend/engine.py`、`smoke_test.py`
- 做：start() 增加 `parallel/prompt_cache_gib/mtp_drafts/mtp_confidence/kv_dtype/backend` 透传（对应 serve --help 实测参数）；新 `ModelSettings` 类：`~/.tensorfold-manager/model_settings.json` 每模型存一份；`load_for(model)` 读取；start 成功后把生效参数回写
- 测试先红：`smoke_test` 断言 start(mock) 后 settings 文件含该模型键与参数值
- 验证：smoke 该项绿

### B2 加载即切换（重叠切换）
- 文件：`backend/engine.py`
- 做：`switch_to(model)` = 起新临时实例探活 ready → 停旧 → 接管端口映射；任一步失败旧实例不动
- 测试：mock 引擎双实例脚本（8080 旧 + 8180 新探活），断言切换后 /v1/models 返回新模型、旧进程已退
- 验证：smoke 该项绿 + 真机后续 E2E 兜底

### B3 update.py（新增）
- 文件：`backend/update.py`、`backend/api.py`
- 做（全部 GitHub，**实测修正：tensorfold 不发 PyPI**，`pypi.org/pypi/tensorfold` 404）：
  - `check_engine()` 查 `https://api.github.com/repos/ashhart/TensorFold/releases/latest`（实测可达，现报 v0.6.5 > 本地 0.6.4）；一键动作 = `git archive <tag>` 拉源码 pip 安装（PyPI pip 路线作废）+ 重启
  - `check_app()` 查 `https://api.github.com/repos/alickfine/TensorFold-Manager/releases`（**注意：latest 端点当前 404，旧稿只有 prerelease** → 取列表过滤 draft，prerelease 也算有效目标）；一键动作 = 打开最新 Release 下载页
  - 后台线程每日一次 + 手动触发；结果缓存；**必须清代理变量**（本机代理坑，同 engine）
- 测试：真联网断言双端点返回结构（引擎必有新版本号；App 无 release 时返回 None 不报错）
- 验证：smoke 该项绿

### B4 chat.py 按会话拆分
- 文件：`backend/chat.py`
- 做：存储从单文件 → `~/.tensorfold-manager/chats/<conv_id>.json`；API：list/create/rename/delete/messages；旧 `history.json` 启动时移到 `archive/`（清空重开）
- 测试：建两个会话、写入、列表读回、删一个再读回
- 验证：smoke 该项绿

### B5 monitor.py 时序采样
- 文件：`backend/monitor.py`
- 做：采样线程 1s 轮询 /metrics + psutil：内存、tok/s（从引擎 metrics 取，取不到则按完成请求估算）、KV 命中率、请求队列数 → 保留 600 点环形缓冲；`history(window)` 出图数据；今日累计（tok/请求/会话）持久化当日文件
- 测试：mock 引擎吐 metrics → 断言 history 长度增长、聚合字段可算
- 验证：smoke 该项绿

## 阶段 C · 壳层（抄 oMLX，风险最高先验证再全铺）

### C0 冒烟 Spike（先做，不通就回来改路线）
- 文件：`shell_spike.py`（临时）
- 做：pyobjc 最小脚本——NSApplication 起窗口 + WKWebView 加载本地 html + window.bridge.postMessage ↔ Python 双向调一次 + NSStatusItem 显图标
- 验证：跑起来能看到窗口和菜单栏图标、控制台打出双向消息。**过不了就停下报告老板**（再议 pywebview 双窗兜底）

### C1 主窗壳
- 文件：新增 `backend/shell.py`（NSWindow 1100×720 可拉伸 + WKWebView + JS 桥全量 API 方法表）
- 验证：能加载 ui/index.html 且 `bridge.call('engine_status')` 返回真数据

### C2 菜单栏
- 文件：新增 `backend/tray.py`（NSStatusItem：图标+tok/s 文字、NSPopover+WKWebView 装 menubar.html、启停/跳转动作）
- 验证：点菜单栏面板「停止引擎」→ 引擎真停、图标变灰（真机验，写入日志）

### C3 入口重构
- 文件：`main.py`（去 pywebview，改 NSApplication 装配 shell/tray/engine/monitor/updater；关主窗=隐藏不退出）
- 验证：`python main.py` 双形态可用

## 阶段 D · 前端（以 tfm2.html 为唯一基准）

### D1 主 UI 落地
- 文件：`ui/index.html`、`ui/style.css`、`ui/app.js`（全量替换）
- 做：从 `prototypes/tfm2.html` 拷贝为起点（令牌/布局/组件零重新发明）；删 mock 数据改 bridge 调用；接 marked+hljs+DOMPurify（资产拷 `ui/vendor/`，来源 oMLX）；模型页三钮/设置弹窗/并发参数/更新区全部接线
- 验证：`prototypes/check.mjs` 改造断言改指 `ui/index.html`（数据改异步后功能断言相应调整），全绿

### D2 菜单栏面板
- 文件：`ui/menubar.html`
- 验证：真机点击各动作生效

### D3 原型↔实现一致性闸门
- 文件：`ui_conformance.py`（新增）
- 做：对比 `ui/index.html` 与 `prototypes/tfm2.html` 的导航项、每卡按钮、设置行、弹窗字段清单（DOM 级），漂移即红
- 验证：闸门 0 漂移；故意删一钮能报

## 阶段 E · 验证与交付

### E1 全量冒烟
- `python smoke_test.py`（B 阶段新增断言在内）全绿

### E2 真机 E2E（验收标准=老板规矩「真实结果」）
- serve 启动→模型页点 Flash 卡「加载」→旧 27B 停新起→对话页选中并聊一句读回→切回 27B→设置改并发→重启生效→菜单栏启停→监控曲线滚动→更新检查出引擎 v0.6.5 新版本号
- 每步截图存 outputs/

### E3 打包发布
- `build_dmg.sh` 产出 v2.0.0 dmg → 挂载跑真引擎验证 → 替换 /Applications → git tag v2.0.0 → push 到 alickfine/TensorFold-Manager（Release 手动传 dmg 可选）

## 风险登记
1. **C0 Spike 是闸门**：pyobjc 壳若在本机自包含运行时翻车，暂停报告，不硬闯
2. oMLX 资产许可：marked/hljs 均 MIT，留 LICENSE 文件即可
3. 重叠切换内存峰值 ~38G：已确认 256G 富余；切换失败保旧实例
4. 本机代理劫持 127.0.0.1：新代码（update/monitor/壳内探活）一律走已验证的「清 PROXY + NO_PROXY」模式
