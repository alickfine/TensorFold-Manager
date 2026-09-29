# TensorFold Manager

独立 macOS App 中的 Web 管理工作台，面向 [TensorFold](https://github.com/ashhart/TensorFold)。参考本机 oMLX 的可适配管理功能，自主设计界面与管理层。

**当前阶段：完整交互原型 v0.2，等待用户验收；真实服务控制尚未实施，GitHub 尚无可安装 DMG。**

## 最终交付：GitHub Releases 中的 DMG

- 安装包：`TensorFold-Manager-<version>-macOS-arm64.dmg`。
- 打开 DMG，将 App 拖入“应用程序”，以独立 macOS App 运行。
- Release 提供 SHA256、App / 引擎版本、macOS 要求、兼容性及已知限制。
- 签名与 Apple 公证状态按真实证书条件和打包结果披露。
- 计划使用隔离引擎运行环境，不依赖或修改现有 oMLX。具体打包方案待正式设计确认。
- 最终验收从 GitHub 下载 DMG，安装、启动、启停服务、切换模型，完成真实 API / 聊天请求。

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

建议架构（待验收）：桌面 App → 独立管理层 / API 网关 → 版本适配器 → 原版 TensorFold。

- App / 引擎独立版本，不侵入上游核心。CLI、服务协议、模型规则和日志格式分别维护兼容测试。
- 上游已有 `tensorfold update --check` / `tensorfold update`，管理层补充隔离环境、版本固定、兼容验证与回退，不直接覆盖当前环境。
- 管理层独立存活；停止引擎后仍可打开界面。模型切换需要停止旧进程，以新模型重启并验证 readiness。
- 统计由管理网关和 runtime / speculative 汇总；缺失值显示“未采集”。保存、启动进程、加载与 API 就绪分别记录。
- 配置原型保存到当前页面内存，刷新即重置；不写真实配置、不保存真实凭据。

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

Superpowers 负责规划。原型验收后以 grill-me 逐项审核升级、排空请求、下载来源、App 生命周期、数据保留和 DMG 打包；用户确认后正式实施。
