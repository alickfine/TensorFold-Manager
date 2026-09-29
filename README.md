# TensorFold Manager

**简体中文** | [English](README.en.md)

独立 macOS App 中的 Web 管理工作台，面向 [TensorFold](https://github.com/ashhart/TensorFold)。参考本机 oMLX 的可适配管理功能，自主设计界面与管理层。

**Apple Silicon 测试版，最新版本见 Releases。** 安装包位于 [GitHub Releases](https://github.com/alickfine/TensorFold-Manager/releases)。真实验证和限制见 [验收记录](docs/acceptance.md)。Ad hoc 签名，未 Apple 公证。

## 最终交付：GitHub Releases 中的 DMG

- 安装包：`TensorFold-Manager-<version>-macOS-arm64.dmg`。
- 打开 DMG，将 App 拖入“应用程序”，以独立 macOS App 运行。
- Release 提供 SHA256、App / 引擎版本、macOS 要求、兼容性及已知限制。
- 签名与 Apple 公证状态按真实证书条件和打包结果披露。
- App 内置独立 Python / uv，主引擎安装在 App 自有版本环境。模型目录可只读扫描既有模型。
- 升级策略：自动检查、手动升级；固定官方 GitHub 提交、候选环境兼容验证、失败恢复旧版本。
- 大模型启动前检查系统内存压力、容量预算与正在运行的推理服务。模型切换采用先停止、确认资源释放、再加载；兼容服务优先复用。
- 最终验收从 GitHub 下载 DMG，安装、启动、启停服务、切换模型，完成真实 API / 聊天请求。

## 安装后使用

1. 打开 App，在“版本与更新”安装主引擎。安装需要联网，采用官方固定提交和独立环境。
2. 在“服务器与目录”设置既有模型目录，或在“模型下载器”下载支持的 checkpoint。第三方镜像不会收到 App 凭据。
3. 在“模型库”扫描模型；未通过目录门禁的本地变体先执行 CLI 兼容验证。
4. 在“运行总览”启动模型；内存压力、预算未知或其他推理服务占用时会给出阻断原因。兼容服务可以只读复用，停止外部服务须确认。
5. 使用“内置聊天”、统计、缓存、日志和简化基准测试。关闭 App 会正常停止它创建的引擎。

正式工作台包含 12 个主菜单。模型配置在模型库的弹窗内；API 端口、集成和认证密钥集中在同一页。启动候选必须完成当前引擎的 MLX 兼容检测，检测不等于权重加载验收。统计显示最多两位小数；缓存显示实际采样时间、数据来源和未采集状态。

模型下载器只展示已支持目录中的模型，选择 Hugging Face 或国内第三方镜像后即可创建下载任务。尚未核实对应 checkpoint 的 ModelScope 映射不提供下载入口。“服务器与目录”可扫描可访问的本地磁盘并登记模型目录；跳过网络卷、应用包和私密应用目录，权限不足或扫描限制会明确显示部分完成。

“版本与更新”的主升级操作包括安装候选、停机前兼容检测、切换和真实 API 验证；正在运行的外部服务会阻断升级，升级失败恢复原模型和原运行参数。高级候选安装、激活和回退操作保留。

界面右上角可选择 **简体中文 / English**，App 会记住语言。模型名称、路径、日志和用户聊天内容保留原文。

## 原型预览

直接打开 `prototype/index.html`。自包含、无构建依赖；指标、密钥、文件、下载、聊天、测试和升级均为模拟，不调用真实服务。

维护源：`prototype/shell.html`、`prototype/app.css`、`prototype/app.js`。修改后运行 `python3 prototype/build.py` 生成独立 HTML。

![完整工作台总览](prototype/overview.png)

### 当前 12 个主页面

| 页面 | 覆盖内容 |
|---|---|
| 运行总览 | 启停服务、当前引擎检测通过的本机模型、运行状态和内存准入 |
| 统计与用量 | 总计和各模型请求、tokens、延迟及导出，最多两位小数 |
| 缓存管理 | 实时 MLX 采样、来源与时间、自有快照和安全清理 |
| 模型库 | 扫描、兼容检测、加载、默认模型、配置弹窗 |
| 模型下载器 | 支持目录选择、HF 官方或国内镜像、下载进度与任务控制 |
| 推理框架配置 | 并行、内存缓存和快照；生成参数位于模型弹窗 |
| 服务器与目录 | 服务器信息、目录设置、本地磁盘扫描与自动登记 |
| API 与集成 | 端点、端口、客户端示例、认证与密钥 |
| 版本与更新 | GitHub 检查、隔离候选安装、手动升级、验证和失败回退 |
| 运行日志 | 紧凑过滤栏、搜索和脱敏导出 |
| 基准测试 | 简单预设、实际吞吐与延迟、取消和结果 |
| 内置聊天 | 消息列表、底部输入、可折叠参数、流式输出、停止与导出 |

历史原型保留旧页面设计，仅供设计记录；其模拟数据和功能不代表当前 App。

## 持续跟进上游

已批准架构：Swift AppKit / WKWebView → 独立管理层 / API 网关 → 版本适配器 → 原版 TensorFold。

- App / 引擎独立版本，不侵入上游核心。CLI、服务协议、模型规则和日志格式分别维护兼容测试。
- 上游已有 `tensorfold update --check` / `tensorfold update`，管理层补充隔离环境、版本固定、兼容验证与回退，不直接覆盖当前环境。
- 管理层独立存活；停止引擎后仍可打开界面。模型切换需要停止旧进程，以新模型重启并验证 readiness。
- 统计由管理网关和 runtime / speculative 汇总；缺失值显示“未采集”。保存、启动进程、加载与 API 就绪分别记录。
- 实际管理层配置、统计、日志与历史位于 App 自有数据目录；管理令牌通过原生桥传入，不放在 URL 或浏览器存储。

## 国内下载与引擎兼容性

- 精确核对上游 checkpoint、drafter、revision、量化 bit / group、架构、分片、tokenizer / template、MTP 文件及许可证。
- `hf-mirror.com` 为第三方镜像，需实际核验来源、版本和文件完整性。
- ModelScope 同名仓库不视为已核实映射；当前简化下载界面不提供尚未核实的映射。
- 有可信 checksum 清单时核验；否则记录 revision、大小、ETag / 文件清单，不宣称所有源均有 SHA256。
- 当前上游明确拒绝图片、音频、视频。VLM、embedding、reranker、diffusion 不展示为已支持接口。
- oMLX 的 ANE、TurboQuant、GDN、Hot / SSD block cache 与 oQ 内核不直接等同迁移；保留适配入口和禁用原因。
- CUDA / EXL3 不作为本机 Apple Silicon 可加载模型。

## 原型验证记录

2026-09-29 真实浏览器逐项点击：16 个主页面、30 个子页均打开，固定验收页面未产生新的浏览器错误日志。

已验证：停止 / 启动、配置保存值保留、编辑模型与运行模型分离、下载入队 / 暂停 / 继续 / 完成、升级激活 / 回退、子 key 新建、基准结果、聊天回复、错误日志过滤及 DMG Release 说明。

**仅证明原型可审阅和交互有效，不代表这些能力已真实实施。**

## 证据与验收流程

核查日期 2026-09-29；上游主分支会变化，实施前必须固定 commit、读回版本。

- [模型与参数](https://github.com/ashhart/TensorFold/blob/main/README.md)、[API 与输入限制](https://github.com/ashhart/TensorFold/blob/main/docs/api.md)
- [CLI](https://github.com/ashhart/TensorFold/blob/main/src/tensorfold/cli.py)、[Hub](https://github.com/ashhart/TensorFold/blob/main/src/tensorfold/hub.py)、[更新实现](https://github.com/ashhart/TensorFold/blob/main/src/tensorfold/update.py)
- [HF 下载文档](https://huggingface.co/docs/huggingface_hub/en/guides/download)、[ModelScope 下载实现](https://github.com/modelscope/modelscope/blob/master/modelscope/hub/snapshot_download.py)
- 本机 oMLX admin 路由、模板、下载、量化、统计、缓存、benchmark 和聊天源码只读盘点；未读用户凭据，未改动现有部署。

Superpowers 负责规划与实施流程，grill-me 审核升级和交付决策；独立子代理并行开发、测试与审查。原型中的模拟数据仅用于设计参考，不能作为实际 App 的运行或验收证据。

## 开发验证

使用 Python 3.12：

```sh
python3.12 -B -m unittest discover -s tests
node --test tests/*.test.mjs
swiftc macos/Bootstrap.swift macos/CredentialRequest.swift macos/tests/main.swift -o /tmp/tfm-native-tests
/tmp/tfm-native-tests
```

打包入口为 `scripts/build-app.py`，需要固定版本的独立 Python 3.12.9 和 uv 0.9.5；GitHub 工作流负责标签对应的 DMG / SHA256。当前测试构建使用 ad hoc 签名，未进行 Apple 公证；不能等同 Developer ID 发行包。
