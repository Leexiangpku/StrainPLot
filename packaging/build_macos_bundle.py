"""构建 macOS 免安装版：dist/StrainPlot-1.0.0-macos.zip

不做交叉编译，也不需要 PyInstaller：产出一个真正的 .app 包，其可执行体是一个
引导脚本（Contents/MacOS/StrainPlot），首次运行时自动建立 venv 并安装依赖，
之后离线可用。想得到完全自带运行时的 .app，请在 macOS 上跑
packaging/macos/build_macos.sh（PyInstaller）。
"""
from __future__ import annotations

import re
import shutil
import stat
import zipfile
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
DIST = ROOT / "dist"


def _read_version() -> str:
    src = (ROOT / "strainplot" / "__init__.py").read_text(encoding="utf-8")
    m = re.search(r'__version__\s*=\s*["\']([^"\']+)', src)
    return m.group(1) if m else "0.0"


VERSION = _read_version()
NAME = "StrainPlot"
STAGE = DIST / f"{NAME}-macos"

LAUNCH = r"""#!/bin/bash
# StrainPlot 引导脚本（由 .app 双击启动）
set -u
HERE="$(cd "$(dirname "$0")" && pwd)"
APP_RES="$(cd "$HERE/../Resources" && pwd)"
SRC_APP="$APP_RES/app"
VENV="$HOME/Library/Application Support/StrainPlot/venv"
PY="$VENV/bin/python"
LOG="$HOME/Library/Application Support/StrainPlot/launch.log"

mkdir -p "$(dirname "$LOG")"
exec 3>>"$LOG"

find_python() {
  for c in python3.12 python3.11 python3.10 python3.9 python3; do
    if command -v "$c" >/dev/null 2>&1; then
      "$c" -c 'import sys; sys.exit(0 if sys.version_info >= (3, 9) else 1)' 2>/dev/null && { echo "$c"; return 0; }
    fi
  done
  return 1
}

fail() {
  echo "$1" >&3
  /usr/bin/osascript -e "display alert \"StrainPlot 启动失败\" message \"$1\" as critical" >/dev/null 2>&1
  exit 1
}

if [ ! -x "$PY" ]; then
  BASE_PY="$(find_python)"
  [ -n "$BASE_PY" ] || fail "未找到 Python 3.9+。请先安装 https://www.python.org/downloads/macos/ 后重试。"
  echo "creating venv with $BASE_PY" >&3
  mkdir -p "$(dirname "$VENV")"
  "$BASE_PY" -m venv "$VENV" >>"$LOG" 2>&1 || fail "创建虚拟环境失败：$BASE_PY"
  "$PY" -m pip install --upgrade pip >>"$LOG" 2>&1
  "$PY" -m pip install pillow numpy openpyxl >>"$LOG" 2>&1 || fail "依赖安装失败（需要联网一次）。详见 $LOG"
fi

"$PY" -c 'import tkinter' 2>/dev/null || fail "当前 Python 缺少 tkinter（Homebrew 版需 brew install python-tk@3.12）。"

PYTHONPATH="$SRC_APP${PYTHONPATH:+:$PYTHONPATH}" "$PY" -m strainplot >>"$LOG" 2>&1
"""

README = """StrainPlot {version} · macOS
========================

双击 StrainPlot.app 即可运行。

这个版本做什么
--------------
通用 X–Y 绘图：程序读入文件夹后，把每个文件**第一行的表头**原样列出来，
你选哪两列就画哪两列（拉伸 / TGA / DSC / UV-Vis / XRD / CV / 滴定 … 都一样），
5 个可编辑预设保存常用组合，`⇄ 反转 X–Y` 一键互换。

首次启动
--------
- 需要本机有 Python 3.9 及以上（推荐 https://www.python.org/downloads/macos/ 安装包，
  它自带 tkinter；Homebrew 的 python 还需 `brew install python-tk@3.12`）；
- 首次运行会自动在 ~/Library/Application Support/StrainPlot/venv 建立独立环境并
  安装 pillow / numpy / openpyxl（需要联网一次），之后离线可用；
- 安装过程窗口会静静地跑几秒，随后弹出主界面。

如果打不开
----------
本包未做 Apple 公证（无开发者账号），系统可能提示“无法验证开发者”：
  · 在 Finder 里右键 StrainPlot.app → 打开 → 再点“打开”；或
  · 终端执行：xattr -dr com.apple.quarantine /path/to/StrainPlot.app
启动失败时查看日志：
  ~/Library/Application Support/StrainPlot/launch.log

想要完全自带运行时（不需要本机 Python）的 .app
------------------------------------------------
在 macOS 上执行：
  bash packaging/macos/build_macos.sh
它会用 PyInstaller 生成带运行时和图标、ad-hoc 签名的 StrainPlot.app 与 .dmg。

功能提要
--------
选择数据文件夹 → 左侧勾选曲线 → 中间实时预览 → 右侧七个标签页调样式 → 导出 PNG/SVG/TIFF/PDF。
默认样式：4×3 inch @600 dpi、Arial Bold、刻度朝内、上/右轴只画轴线；轴标题自动转英文。
样式模板与读取预设保存在 ~/.strainplot/。
""".format(version=VERSION)

REQUIREMENTS = "pillow>=9.0\nnumpy>=1.22\nopenpyxl>=3.0\n"


def _add(zf: zipfile.ZipFile, path: Path, arcname: str, mode: int = 0o644) -> None:
    zi = zipfile.ZipInfo(arcname, date_time=(2026, 1, 1, 0, 0, 0))
    zi.external_attr = (stat.S_IFREG | mode) << 16
    zi.compress_type = zipfile.ZIP_DEFLATED
    zf.writestr(zi, path.read_bytes())


def main() -> None:
    if STAGE.exists():
        shutil.rmtree(STAGE)
    app = STAGE / f"{NAME}.app"
    macos = app / "Contents" / "MacOS"
    res = app / "Contents" / "Resources"
    macos.mkdir(parents=True)
    (res / "app").mkdir(parents=True)

    shutil.copytree(ROOT / "strainplot", res / "app" / "strainplot",
                    ignore=shutil.ignore_patterns("__pycache__", "*.pyc"))
    shutil.copy2(ROOT / "packaging" / "icon.icns", res / "icon.icns")
    (app / "Contents" / "Info.plist").write_bytes(
        (ROOT / "packaging" / "macos" / "Info.plist").read_bytes())
    (STAGE / "README-macOS.txt").write_text(README, encoding="utf-8", newline="\n")
    (STAGE / "requirements.txt").write_text(REQUIREMENTS, encoding="utf-8", newline="\n")
    shutil.copy2(ROOT / "packaging" / "macos" / "StrainPlot.command", STAGE / "StrainPlot.command")

    zip_path = DIST / f"StrainPlot-{VERSION}-macos.zip"
    if zip_path.exists():
        zip_path.unlink()
    with zipfile.ZipFile(zip_path, "w", zipfile.ZIP_DEFLATED, compresslevel=9) as zf:
        _add(zf, STAGE / "README-macOS.txt", f"{NAME}/README-macOS.txt")
        _add(zf, STAGE / "requirements.txt", f"{NAME}/requirements.txt")
        _add(zf, STAGE / "StrainPlot.command", f"{NAME}/StrainPlot.command", 0o755)
        _add(zf, app / "Contents" / "Info.plist", f"{NAME}/{NAME}.app/Contents/Info.plist")
        _add(zf, res / "icon.icns", f"{NAME}/{NAME}.app/Contents/Resources/icon.icns")
        # 引导脚本：755 权限，Finder 双击即运行
        zi = zipfile.ZipInfo(f"{NAME}/{NAME}.app/Contents/MacOS/{NAME}", (2026, 1, 1, 0, 0, 0))
        zi.external_attr = (stat.S_IFREG | 0o755) << 16
        zi.compress_type = zipfile.ZIP_DEFLATED
        zf.writestr(zi, LAUNCH.replace("\r\n", "\n").encode("utf-8"))
        for f in sorted((res / "app").rglob("*")):
            if f.is_file():
                arc = f"{NAME}/{NAME}.app/Contents/Resources/app/{f.relative_to(res / 'app').as_posix()}"
                _add(zf, f, arc)

    print(f"zip -> {zip_path}  {zip_path.stat().st_size / 1024:.0f} KB")
    print("解压后双击 StrainPlot.app 即可（需本机 Python 3.9+，首次联网装依赖）")


if __name__ == "__main__":
    main()
