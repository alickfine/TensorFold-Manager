# TensorFold Manager 实施验收记录

状态：实施中，尚未发布最终 DMG。原型验收与真实 App 验收分别记录。

## 已有新鲜证据（2026-09-29，本机 macOS 27 / arm64）

| 项目 | 实际结果 | 范围 |
|---|---|---|
| 原生 App + WebKit 管理令牌桥 | 多个真实管理实例启动，令牌留在 JS 模块闭包 | localhost 管理服务，未暴露明文令牌 |
| 隔离主引擎安装 | v0.3.6.2，commit `71377a5373ed7b394f1b480ba2a6a3986b03af1c` | 官方固定提交，App 自有 venv |
| 本地变体兼容预检 | Qwen3.8-27B-oQ4e-mtp CLI info 成功 | 不把 CLI 成功当成权重来源证明 |
| 真实模型启动 / 请求 | App 所属引擎 PID 31852 启动；真实聊天状态 200，13 input / 359 output tokens | 当前本地 Qwen 变体；非模拟引擎 |
| 正常 App 退出清理 | 关闭 parent pipe 后 PID 31852 消失、18080 不再监听 | 仅 App 创建的进程 |
| 启动后严格签名 | app-smoke-7 实际启动 / 浏览 / 退出后 `codesign --verify --deep --strict` 成功 | ad hoc，未 Apple 公证 |
| 安装位置变化 | 复制至 `build/relocation test/TensorFold Manager.app`，真实 Web 管理实例启动 | 带空格路径；稳定运行时复制目录 |
| 卡住退出 | 暂停 App 自有 manager PID 37185，退出 125 秒后显示继续等待 / 显式强制退出；选择后 manager 和 App 都退出 | 未运行模型，没有外部服务停止 |
| 运行时完整性 | 完整实际签名文件 manifest；stdlib 改动、内容损坏和未登记文件 fixture 检查通过 | 每次启动校验稳定副本 |
| Native 校验 | bootstrap / origin / export / credential scope / runtime integrity checks 通过 | Keychain 只测输入解析，未读写真实 token |

## 本次集成证据（仍不代表最终验收）

- 内存准入使用 macOS 容量、可回收内存和压力采样，预留系统容量，模型权重 / KV / 并发 / 缓存按保守预算计入。进程 RSS 不作为模型峰值预算。
- 同数据目录管理实例锁与全局重任务锁已实现。已有兼容 TensorFold 服务可只读接入；接入服务不会随 App 退出而停止。
- 下载认证仅通过 App 自有凭据显式启用，官方精确域名可接收对应 token，第三方镜像禁止携带 token，跳转剥离认证头。4 项新增凭据边界测试及原下载测试通过；未操作真实 Keychain。
- 参考答案测试页已接入题目添加 / 删除、真实结果、部分结果和取消队列。评分为参考文本相等 / 包含，不代表通用知识准确率。
- 真实 loopback 管理 HTTP 集成检查：state、resources、services、tools、accuracy、downloads/catalog、cache、stats、keys、profiles、logs、benchmark/results、updates 均返回 200。此次未启动模型、未停止外部服务。
- 前一集成快照 Python 全套 119 tests、Web 22 tests 通过；当前进程连接校验与界面仍在更新，最终集成后必须重新验证。

## 待完成

- 内存 / 服务门禁与外部切换的真实 App 界面及模型切换验收；完成独立审查。
- 标准 MLX 转换、HF 上传范围预览及 App 自有凭据集成。
- 参考答案队列的真实模型测试、高级参数及完整指标展示。
- 新协议的真实端到端验收、模型切换与下载、独立安全和全分支审查。
- DMG 挂载 / 安装 / 最终启动、公开源码同步、GitHub Release 和 SHA256。

不能以当前单项通过替代最终安装包与业务闭环验收。部署目标 macOS 14；本记录仅证明本机 macOS 27 实际结果。

## 新增下载与资源证据（仍实施中）

- 官方 Hugging Face 固定提交 `0d77464eeb233a2da68ebf9d7dc4ef46` 的 `mlx-community/gemma-4-26b-a4b-it-4bit` 实际下载完成：12 文件，15,373,588,575 bytes，各文件 SHA256 / Git blob 校验通过；隔离 TensorFold CLI info 成功。尚未加载该模型。
- 标准 MLX 工具隔离安装完成：mlx-lm 0.31.3、huggingface_hub 1.33.0，完整 freeze 与来源记录已保存；真实 convert CLI help 参数验证通过。尚未进行真实转换。
- ModelScope 实际官方文件树与 config 下载校验通过。无全仓提交时逐文件固定其 immutable revision，界面标为文件树快照，避免把分支名当成固定提交。
- 工具转换现要求完整资源采样和真实 OS 重任务锁，不再允许仅检查单一端口或线程锁的降级路径。2 项拒绝降级、12 项工具、6 项监督器测试通过。
- 169.23 GiB 的本地 GLM 权重在保守驻留与最小上下文预算下仍超出本机系统预留后的容量，因此当前禁止启动；不会为让模型启动而缩小安全预算。
- 独立审查要求在发送任何请求前，核验已连接 TCP 四元组的实际服务进程身份；相关修正和审查未完成前继续暂停真实模型加载。
