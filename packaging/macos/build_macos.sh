#!/usr/bin/env bash
# 一键构建可独立运行的 StrainPlot.app（macOS）
#
#   ./packaging/macos/build_macos.sh            # 只构建 .app
#   ./packaging/macos/build_macos.sh --dmg      # 另外打包成 .dmg（失败则退回 zip）
#
# 为什么不用系统 Python：macOS 自带的 /usr/bin/python3 只有 Tk 8.5，
# 在新版 macOS 上会直接报 "macOS 14 (1408) or later required, have instead 14 (1406) !"。
# 所以这里下载 python-build-standalone 的 CPython（自带 Tk 9）建独立环境，
# 打出来的 .app 自带运行时，目标机器不需要装 Python、也不需要联网。
#
# 只有第一次需要联网（约 23 MB 运行时 + 若干 wheel），之后离线可重复构建。
set -euo pipefail

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/../.." && pwd)"
cd "$ROOT"

BUILD="$ROOT/.build"
PBASE="$BUILD/python"                      # python-build-standalone 解压后的运行时
VENV="$BUILD/venv"
DIST="$ROOT/dist"
APP="$DIST/StrainPlot.app"
SAMPLES="$ROOT/示例"

PBS_TAG="20261020"
PBS_PY="3.12.15"

MAKE_DMG=0
for arg in "$@"; do
    case "$arg" in
        --dmg) MAKE_DMG=1 ;;
        -h|--help) sed -n '2,12p' "$0"; exit 0 ;;
    esac
done

say() { printf '\033[1m==> %s\033[0m\n' "$*"; }

# ---------------------------------------------------------------- 运行时 --
if [[ ! -x "$PBASE/bin/python3" ]]; then
    case "$(uname -m)" in
        arm64)  PBS_ARCH="aarch64" ;;
        x86_64) PBS_ARCH="x86_64" ;;
        *) echo "不支持的架构：$(uname -m)" >&2; exit 1 ;;
    esac
    NAME="cpython-${PBS_PY}+${PBS_TAG}-${PBS_ARCH}-apple-darwin-install_only.tar.gz"
    URL="${PYTHON_URL:-https://github.com/astral-sh/python-build-standalone/releases/download/${PBS_TAG}/${NAME}}"
    mkdir -p "$BUILD/cache"
    if [[ ! -f "$BUILD/cache/$NAME" ]]; then
        say "下载自带 Tk 9 的 Python 运行时（$PBS_ARCH，约 23 MB）"
        curl -fL --retry 3 -o "$BUILD/cache/$NAME" "$URL"
    fi
    say "解压运行时"
    rm -rf "$PBASE"
    tar xzf "$BUILD/cache/$NAME" -C "$BUILD"
    [[ -x "$PBASE/bin/python3" ]] || { echo "解压后找不到 $PBASE/bin/python3" >&2; exit 1; }
fi

# ------------------------------------------------------------------ venv --
if [[ ! -x "$VENV/bin/pyinstaller" ]]; then
    say "创建构建环境（首次需要联网装依赖）"
    rm -rf "$VENV"
    "$PBASE/bin/python3" -m venv "$VENV"
    "$VENV/bin/python" -m pip install -q --upgrade pip
    "$VENV/bin/python" -m pip install -q pillow numpy openpyxl pyinstaller
fi

# ----------------------------------------------------------------- 构建 --
say "PyInstaller 打包"
rm -rf "$DIST"
# PYINSTALLER_CONFIG_DIR：默认写在 ~/Library/Application Support，受限环境会 PermissionError
PYINSTALLER_CONFIG_DIR="$BUILD/pyi-config" \
    "$VENV/bin/pyinstaller" --noconfirm --clean \
    --distpath "$DIST" --workpath "$BUILD/pyi" \
    packaging/macos/StrainPlot.spec

# ------------------------------------------------------------- 示例数据 --
if [[ -d "$SAMPLES" ]]; then
    say "内置示例数据（只带解析用得到的 CSV）"
    DEST="$APP/Contents/Resources/示例"
    rm -rf "$DEST"
    mkdir -p "$DEST"
    ( cd "$SAMPLES" && find . -name '*.csv' -print0 | while IFS= read -r -d '' f; do
        mkdir -p "$DEST/$(dirname "$f")"
        cp "$f" "$DEST/$f"
    done )
    echo "    $(find "$DEST" -name '*.csv' | wc -l | tr -d ' ') 个 CSV → Contents/Resources/示例"
fi

# ----------------------------------------------------------------- 签名 --
say "ad-hoc 签名（未公证：首次打开需右键 → 打开）"
codesign --force --deep --sign - "$APP" >/dev/null 2>&1 || true
xattr -cr "$APP" 2>/dev/null || true
codesign --verify --deep --strict "$APP" && echo "    签名校验通过"

# ----------------------------------------------------------------- 自检 --
say "自检（在打包好的 .app 里读数据 → 建图 → 出 PNG）"
"$APP/Contents/MacOS/StrainPlot" --selftest || echo "    （自检未通过，见上方输出）"

# ----------------------------------------------------------- dmg / zip --
if [[ $MAKE_DMG -eq 1 ]]; then
    say "打包分发文件"
    STAGE="$BUILD/dmg"
    rm -rf "$STAGE" && mkdir -p "$STAGE"
    cp -R "$APP" "$STAGE/"
    ln -s /Applications "$STAGE/Applications"
    rm -f "$DIST/StrainPlot.dmg"
    if hdiutil create -volname "StrainPlot" -srcfolder "$STAGE" -ov -format UDZO \
        "$DIST/StrainPlot.dmg" >/dev/null 2>&1; then
        echo "    $DIST/StrainPlot.dmg"
    else
        echo "    hdiutil 不可用，改用 zip"
        ditto -c -k --sequesterRsrc --keepParent "$APP" "$DIST/StrainPlot-macOS.zip"
        echo "    $DIST/StrainPlot-macOS.zip"
    fi
fi

echo
echo "完成：$APP"
du -sh "$APP" 2>/dev/null || true
