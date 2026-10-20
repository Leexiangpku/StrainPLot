#!/bin/bash
# 在 macOS 上打包 StrainPlot.app（含 .dmg 可选）
#
# 前置：macOS + Python 3.9+（推荐 python.org 版本，自带 tkinter）
# 用法：bash packaging/macos/build_macos.sh
#
# 说明：PyInstaller 不能跨平台编译，macOS 版必须在 macOS 上执行本脚本。
set -euo pipefail

ROOT="$(cd "$(dirname "$0")/../.." && pwd)"
cd "$ROOT"
VERSION="1.0.0"
APP="StrainPlot"
DIST="$ROOT/dist"

echo "==> 检查 Python"
PY="${PYTHON:-python3}"
"$PY" -c 'import sys; assert sys.version_info >= (3, 9), sys.version' || {
  echo "需要 Python 3.9+"; exit 1; }
"$PY" -c 'import tkinter' || {
  echo "当前 Python 缺少 tkinter（Homebrew：brew install python-tk@3.12）"; exit 1; }

echo "==> 安装打包依赖"
"$PY" -m pip install --upgrade pip
"$PY" -m pip install pyinstaller pillow numpy openpyxl

echo "==> 准备图标"
"$PY" "$ROOT/packaging/make_icons.py"

echo "==> PyInstaller 打包"
rm -rf "$ROOT/build" "$DIST/$APP.app"
"$PY" -m PyInstaller \
  --noconfirm --clean --windowed --name "$APP" \
  --icon "$ROOT/packaging/icon.icns" \
  --osx-bundle-identifier "com.strainplot.app" \
  --add-data "$ROOT/strainplot:strainplot" \
  --hidden-import "PIL._tkinter_finder" \
  --collect-submodules "openpyxl" \
  --paths "$ROOT" \
  "$ROOT/packaging/win/run_app.py"

echo "==> 写入 Info.plist 补充字段"
PLIST="$DIST/$APP.app/Contents/Info.plist"
if [ -f "$PLIST" ]; then
  /usr/libexec/PlistBuddy -c "Set :CFBundleShortVersionString $VERSION" "$PLIST" 2>/dev/null || true
  /usr/libexec/PlistBuddy -c "Set :NSHighResolutionCapable true" "$PLIST" 2>/dev/null || true
  /usr/libexec/PlistBuddy -c "Add :LSMinimumSystemVersion string 10.15" "$PLIST" 2>/dev/null || true
fi

echo "==> ad-hoc 签名（未公证，Gatekeeper 首次需右键打开）"
codesign --force --deep --sign - "$DIST/$APP.app" || echo "（签名失败可忽略，右键→打开即可运行）"

echo "==> 生成 dmg"
if command -v hdiutil >/dev/null 2>&1; then
  rm -f "$DIST/${APP}-${VERSION}-macos.dmg"
  hdiutil create -volname "$APP" -srcfolder "$DIST/$APP.app" -ov -format UDZO \
    "$DIST/${APP}-${VERSION}-macos.dmg" >/dev/null
  echo "dmg -> $DIST/${APP}-${VERSION}-macos.dmg"
fi

echo "完成：$DIST/$APP.app"
