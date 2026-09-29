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
5. 使用“内置聊天”、统计、缓存、日志、基准和参考答案测试。关闭 App 会正常停止它创建的引擎。

正式工作台包含 17 个菜单。上游没有稳定接口的能力会显示不可用原因，运行指标只显示实际采集值。量化需安装独立模型工具；目标格式由当前主引擎预检，转换输出使用独立受管目录，源权重保持只读。

界面右上角可选择 **简体中文 / English**，App 会记住语言。模型名称、路径、日志和用户聊天内容保留原文。

## 原型预览

直接打开 `prototype/index.html`。自包含、无构建依赖；指标、密钥、文件、下载、聊天、测试和升级均为模拟，不调用真实服务。

维护源：`prototype/shell.html`、`prototype/app.css`、`prototype/app.js`。修改后运行 `python3 prototype/build.py` 生成独立 HTML。

![完整工作台总览](prototype/overview.png)

### 16 个主页面

| 页面 | 覆盖内容 |
|---|---|
| 运行总览 | 启停 / 重启、活动模型、请求、内存、缓存、端点、版本和布局 |
| 统计与用量 | 本次运行 / 累计总计、各模型统计、tokens、TTFT、decode、失败 / 取消和导出 |
| 缓存管理 | MLX active / allocator cache / peak、Prompt cache、checkpoint、spill、快照、各模型缓存和清理确认 |
| 模型库 | 官方 checkpoint、本地目录扫描、加载 / 切换、默认 / 收藏 / 隐藏和辅助模型 |
| 模型下载器 | HF 官方、国内第三方镜像、ModelScope、revision / 映射核验、暂停 / 继续 / 取消 / 重试 |
| 模型配置 | 采样、上下文、thinking、MTP / draft、Profile / Template / Recipe、API 别名和能力门禁 |
| 量化与上传 | 独立输出、格式预检、MTP 保留、HF 上传范围 / 可见性、模型文件检查 |
| 推理框架配置 | 后端、并行、默认生成、内存 / 缓存、参数能力、保存与实际生效状态 |
| 服务器与目录 | 主机、进程、监听 / 管理 / 引擎端口、模型 / 草稿 / 下载 / 数据目录、App 生命周期 |
| API 与集成 | 端点、模型列表、curl / 客户端模板、MCP、文档转文本、搜索和协议桥接边界 |
| 认证与密钥 | 管理会话、主 key / 子 key、权限 / 过期、轮换、各下载和上传来源凭据隔离 |
| 版本与更新 | 主引擎 / App / 依赖、GitHub 检查、隔离升级、兼容与冒烟验证、回退、DMG 发行 |
| 运行日志 | 当前 / 历史、等级 / 搜索、刷新 / 滚动偏好、脱敏导出和失败诊断 |
| 基准测试 | 吞吐 / TTFT / prefill / decode、上下文压力、准确性、drafted / serial、cold / warm、外部端点 |
| 内置聊天 | 多轮、采样 / System prompt、停止、reasoning / tools、Markdown 展示设计、每轮性能与导出 |
| 功能适配表 | 上游原生、管理层新增、oMLX 专属和当前不支持能力逐项对照 |

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
- ModelScope 由管理层官方下载适配到本地目录，再交给 TensorFold。官方 HF checkpoint 的国内映射尚未证实，不能根据名称自动替代。
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
