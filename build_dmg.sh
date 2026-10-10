#!/bin/zsh
# 打自包含 .dmg：.app 内嵌 runtime（standalone python + tensorfold/mlx/pyobjc）
# 布局: .app/Contents/Resources/{app(代码),runtime(解释器+site-packages)}
set -eu
SRC="$(cd "$(dirname "$0")" && pwd)"
RT="${1:-/tmp/tfbuild/pkg/runtime}"
[ -x "$RT/bin/python3" ] || { echo "runtime 缺失: $RT"; exit 1; }
[ -d "$RT/lib/python3.12/site-packages/tensorfold" ] || { echo "runtime 里没有 tensorfold"; exit 1; }
"$RT/bin/python3" -c "import AppKit, WebKit, Quartz, psutil" 2>/dev/null || { echo "runtime 缺少壳层依赖(AppKit/WebKit/Quartz/psutil)"; exit 1; }

BUILD="$SRC/dist/build"
DMG="$SRC/dist/TensorFold Manager.dmg"
APP="$BUILD/TensorFold Manager.app"
rm -rf "$BUILD" "$DMG"
mkdir -p "$APP/Contents/MacOS" "$APP/Contents/Resources/app"

cat > "$APP/Contents/Info.plist" <<'PLIST'
<?xml version="1.0" encoding="UTF-8"?>
<!DOCTYPE plist PUBLIC "-//Apple//DTD PLIST 1.0//EN" "http://www.apple.com/DTDs/PropertyList-1.0.dtd">
<plist version="1.0"><dict>
  <key>CFBundleName</key><string>TensorFold Manager</string>
  <key>CFBundleDisplayName</key><string>TensorFold Manager</string>
  <key>CFBundleIdentifier</key><string>local.tensorfold.manager</string>
  <key>CFBundleVersion</key><string>2.1.7</string>
  <key>CFBundleShortVersionString</key><string>2.1.7</string>
  <key>CFBundleExecutable</key><string>TensorFoldManager</string>
  <key>CFBundlePackageType</key><string>APPL</string>
  <key>LSMinimumSystemVersion</key><string>13.0</string>
  <key>NSHighResolutionCapable</key><true/>
  <key>NSSupportsAutomaticGraphicsSwitching</key><true/>
</dict></plist>
PLIST

cp "$SRC/launcher.sh" "$APP/Contents/MacOS/TensorFoldManager"
chmod +x "$APP/Contents/MacOS/TensorFoldManager"

cp -R "$SRC/backend" "$APP/Contents/Resources/app/backend"
cp -R "$SRC/ui" "$APP/Contents/Resources/app/ui"
cp "$SRC/main.py" "$APP/Contents/Resources/app/main.py"

# 内嵌运行时（standalone python + site-packages 里的 mlx/tensorfold 等）
ditto "$RT" "$APP/Contents/Resources/runtime"

codesign --force --deep --sign - "$APP" 2>/dev/null || echo "codesign skipped"

mkdir -p "$BUILD/dmgroot"
mv "$APP" "$BUILD/dmgroot/TensorFold Manager.app"
ln -s /Applications "$BUILD/dmgroot/Applications"
cat > "$BUILD/dmgroot/README-安装说明.txt" <<'TXT'
TensorFold Manager v2.1.7 —— 本地 LLM 推理引擎管理端（Apple Silicon 专用）

安装：把 "TensorFold Manager.app" 拖到「应用」文件夹（或直接双击运行本卷里的 App）。
如已安装旧版，先移除旧版再拖入。

App 自带内嵌 Python 运行时（TensorFold 引擎 + MLX + 原生 macOS 壳），无需另装任何依赖。
模型缓存沿用系统目录 ~/.cache/huggingface，不占 App 体积；大模型首次加载约 30-60s。

v2.1.7 新特性：
- 窗口自适应：不再有被遮挡/裁掉的内容与按钮（主区按内容高度排布并纵向滚动，
  窄窗口自动降列；此前从 900x600 到 1280x800 每一档设置页底部都丢内容且滚不到）；
- 升级引擎按钮修好：壳层补上 WKWebView 的原生对话框委托，确认框改走应用内实现
  （此前 confirm() 在 WKWebView 里恒返 false，按钮点了不弹窗、不报错、什么都不发生）；
- 同一问题一并修好的还有「删除缓存 / 清除累计用量 / 重启实例」三个按钮；
- 升级成功后状态行自动收口为「已是最新」，不再挂着一个已经没用的升级按钮。

v2.1.6 新特性：
- 更新状态行永远有结果：未检查 / 发现新版本（含当前→最新）/ 已是最新 / 检查失败（原因留在页面上）；
- 版本号归一：不再显示 "tensorfold-native 1.0.2" 这种 CLI 自报原文；
- 「检查更新」按钮有进行中状态，检查结论同时给在提示与页面上。

v2.1.5 新特性：
- 本机性能：真实显示 CPU 核心构成（P/E 核 + 逻辑核）、每核占用格子、GPU 型号与核心数、系统负载；
- 实时读数修复：抓取频率与界面刷新解耦，数字不再时有时无；速率改用真解码耗时做分母；
- 累计用量：Manager 侧记账（跨引擎重启持续、单调不减），可切会话/累计口径并清除；
- 监听范围：仅本机(127.0.0.1) / 局域网(0.0.0.0) 一键切换，对话代理即刻重绑；换地址后一键重启实例；
- 默认上下文多档：32k/64k/128k/256k/512k/1M 下拉 + 手动输入；
- 对话模型下拉只显示模型名（去掉了"未加载/自动拉起"等后缀）。

v2 新特性：
- 多实例并行：可同时加载多个模型，各自独立端口/日志/监控；
- 原生壳：主窗口 + 菜单栏常驻，关窗不退出，托盘直接启停模型；
- 每模型参数：上下文/采样/MTP 推测解码/并发等按模型保存，弹窗修改即时生效；
- 加速配套联动：主模型卡片直接显示草稿模型状态，设置里可一键下载并开关推测解码；
- 对话增强：流式输出、Markdown/代码高亮、多会话管理；
- 自动更新：检查 TensorFold 引擎与 App 新版本，引擎一键升级。

用法：
1. 双击打开 App；
2. 「模型」页下载模型（约 15-20GB 起）；
3. 「加载」启动模型（可同时加载多个）；
4. 「对话」页聊天，「监控」页看 tok/s 与内存，「设置」页调参数与检查更新。

支持模型族: Nemotron3.5-Lightning-30B / Qwen3.8-27B / Qwen3.8-Flash-Next-MTP
/ GLM-5.3-Flash / Qwen3.6-35B-A3B / DeepSeek-V4-Flash（及自定义 HF repo id）。
TXT

hdiutil create -volname "TensorFold Manager" -srcfolder "$BUILD/dmgroot" \
  -ov -format UDZO -fs HFS+ -imagekey zlib-level=9 "$DMG"
ls -lh "$DMG"
echo "DMG OK -> $DMG"
