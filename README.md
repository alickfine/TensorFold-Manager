# TensorFold Manager (Mac) v2.0.0

本地 [TensorFold](https://github.com/ashhart/TensorFold) 推理引擎的 Mac 管理端（Apple Silicon 专用）：多实例加载模型、下载/删除模型、流式对话、监控 tok/s 与内存、菜单栏常驻、自动更新。

## 下载与安装

到 [Releases](../../releases) 下载 `TensorFold Manager.dmg`，挂载后把 App 拖进「应用」即可。
App 自包含内嵌运行时（Python 3.12 + TensorFold + MLX + 原生 macOS 壳），不依赖本机任何 venv；模型缓存在 `~/.cache/huggingface`，不占 App 体积。

## 特性

- **多实例并行**：同时加载多个模型，各自独立进程 / 端口 / 日志 / 监控；内存闸门防止过量加载。
- **原生壳**：NSWindow + WKWebView 主窗 + 菜单栏常驻（关窗不退出，托盘直接启停模型）。
- **每模型参数**：上下文 / 采样 / MTP 推测解码 / 并发等按模型保存（`~/.tensorfold-manager/model_settings.json`），弹窗修改、保存并重启引擎即时生效。优先级：本次调用 > 每模型已存 > 全局默认。
- **对话**：SSE 流式输出、Markdown + 代码高亮、多会话持久化（`~/.tensorfold-manager/chats/`）。
- **监控**：解码 tok/s、KV 占用、引擎内存足迹、空闲内存曲线（1Hz 聚合各实例 `/metrics` + psutil），每实例明细。
- **更新**：检查 TensorFold 引擎与 App 新版本（GitHub），引擎一键升级。

## 开发

```bash
# 源码直跑（Python ≥3.11 venv，装 tensorfold、pyobjc、psutil）
python main.py

# 冒烟测试（47 断言，FakeProc/FakeServer，不需要真引擎）
python smoke_test.py

# UI 契约闸门（38 断言，Chrome CDP 对 DOM 逐项对账原型）
node ui_conformance.mjs

# 真机 E2E（需 Apple Silicon + 已缓存模型）
python e2e_real.py

# 重打自包含 dmg（runtime 目录含 python3.12 + tensorfold + pyobjc；可复用已装 App 的 Contents/Resources/runtime）
./build_dmg.sh [runtime目录]
```

入口找引擎的顺序：同级 `runtime/` 内嵌运行时 → `~/.workbuddy/binaries/python/envs/default` venv；`TFM_CLI` 环境变量可覆盖。

## 已知边界

- 上下文默认 32768，256GB 机器跑 27B-4bit 富余；更大模型按需调小或改 `serve` 参数。
- 引擎子进程环境清除了 HTTP(S)_PROXY 并强制 NO_PROXY=127.0.0.1 —— 规避系统代理劫持本地回环流量（实测会被 502）。
- 外部程序可直连引擎的 OpenAI 兼容端点（默认 8080 起自动分配），或在设置页复制 API 端点。
