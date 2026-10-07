#!/bin/zsh
# 打包 TensorFold Manager.app —— 只复制文件，不编译
set -eu
SRC="$(cd "$(dirname "$0")" && pwd)"
OUT="$SRC/dist"
APP="$OUT/TensorFold Manager.app"
rm -rf "$APP"
mkdir -p "$APP/Contents/MacOS" "$APP/Contents/Resources/app"

cat > "$APP/Contents/Info.plist" <<'PLIST'
<?xml version="1.0" encoding="UTF-8"?>
<!DOCTYPE plist PUBLIC "-//Apple//DTD PLIST 1.0//EN" "http://www.apple.com/DTDs/PropertyList-1.0.dtd">
<plist version="1.0"><dict>
  <key>CFBundleName</key><string>TensorFold Manager</string>
  <key>CFBundleDisplayName</key><string>TensorFold Manager</string>
  <key>CFBundleIdentifier</key><string>local.tensorfold.manager</string>
  <key>CFBundleVersion</key><string>1.0.0</string>
  <key>CFBundleShortVersionString</key><string>1.0.0</string>
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

codesign --force --sign - "$APP" 2>/dev/null || echo "codesign skipped"
echo "OK -> $APP"
