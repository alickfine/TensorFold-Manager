#!/bin/zsh
# TensorFold Manager launcher — 被 .app 的 MacOS 可执行文件调用
set -u
SCRIPTDIR="$(cd "$(dirname "$0")" && pwd)"
# .app 布局: Contents/MacOS/launcher → ../Resources/{app,runtime}；源码直跑: 脚本同目录
RES="$(dirname "$SCRIPTDIR")/Resources"
APP="$RES/app"
[ -f "$APP/main.py" ] || APP="$SCRIPTDIR"

# 优先 .app 内嵌运行时（自包含）；退回本机隔离 venv；再退回 PATH python3
PY="$RES/runtime/bin/python3"
[ -x "$PY" ] || PY="$HOME/.workbuddy/binaries/python/envs/default/bin/python3"
[ -x "$PY" ] || PY="$(command -v python3 || true)"
if [ -z "$PY" ] || [ ! -x "$PY" ]; then
  osascript -e 'display alert "TensorFold Manager" message "未找到 Python 3.11+，无法启动。"' &
  exit 1
fi

exec "$PY" "$APP/main.py"
