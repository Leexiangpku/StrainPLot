"""构建 Windows 免安装版：dist/StrainPlot-win64/ + zip。

用法（任意 Python 3.9+，本机即可）：
    python packaging/build_win_portable.py

做法：把当前解释器（含 numpy / Pillow / openpyxl / tkinter）复制成 runtime/，
配上 app/strainplot 源码与用 csc.exe 编译的 StrainPlot.exe 启动器。
"""
from __future__ import annotations

import shutil
import subprocess
import sys
import zipfile
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
DIST = ROOT / "dist"
NAME = "StrainPlot-win64"
APP_NAME = "StrainPlot"
VERSION = "1.0.0"

SRC_PY = Path(sys.base_prefix)
SRC_PKG = ROOT / "strainplot"

# site-packages 里本项目用不到的包（体积大户）
SKIP_SITE = {
    "pandas", "pandas.libs", "pip", "docx", "pptx", "xlsxwriter", "lxml",
    "tzdata", "dateutil", "__pycache__", "typing_extensions.py",
    "_pytest", "pytest", "setuptools", "pkg_resources", "wheel",
}
# 标准库里用不到的部分
SKIP_LIB = {
    "test", "idlelib", "lib2to3", "ensurepip", "turtledemo", "distutils",
    "site-packages",  # 单独处理
}

README = """StrainPlot 1.0.0  (Windows 64 位免安装版)
========================================

双击 StrainPlot.exe 即可运行，无需安装 Python。

第一次使用
----------
1. 双击 StrainPlot.exe；
2. 点左上角「选择数据文件夹」，选中装有 Instron 数据的文件夹
   （里面应有 *.is_tens 与同名 xxx.is_tens_RawData\\Specimen_RawData_*.csv，
    或 Excel / CSV 表格）；
3. 左侧勾选曲线，中间实时预览，右侧六个标签页调样式；
4. 右上角「导出图片」输出 PNG / SVG / TIFF / PDF。

目录说明
--------
StrainPlot.exe      启动器
app\\                程序本体（Python 源码）
runtime\\            自带的 Python 3.12 运行时（含 numpy / Pillow / openpyxl / tkinter）
strainplot.log      运行日志（启动异常时先看这个）

样式模板保存在 %USERPROFILE%\\.strainplot\\ 下，可复制到别的电脑复用。

制图默认值
----------
4 x 3 inch @ 600 dpi；Arial Bold；刻度朝内；上/右轴只画轴线不画刻度；
Strain-Stress 轴标题；数据范围上下各留 10%。

遇到问题
--------
- 双击没反应：看 strainplot.log；
- 提示缺少 VCRUNTIME140.dll：安装「Microsoft Visual C++ 2015-2022 运行库 (x64)」；
- 系统要求：Windows 10 / 11 64 位。
"""


def _ignore_site(dirname: str, names: list[str]) -> set[str]:
    return {n for n in names if n in SKIP_SITE or n.startswith("__pycache__")}


def copy_runtime(dst: Path) -> None:
    if dst.exists():
        shutil.rmtree(dst)
    dst.mkdir(parents=True)

    for item in SRC_PY.iterdir():
        name = item.name
        if name == "Lib":
            continue
        if item.is_dir():
            shutil.copytree(item, dst / name, ignore=shutil.ignore_patterns("__pycache__", "test", "tests"))
        else:
            shutil.copy2(item, dst / name)

    lib_dst = dst / "Lib"
    lib_dst.mkdir()
    for item in (SRC_PY / "Lib").iterdir():
        if item.name in SKIP_LIB or item.name.startswith("__pycache__"):
            continue
        if item.is_dir():
            shutil.copytree(item, lib_dst / item.name,
                            ignore=shutil.ignore_patterns("__pycache__", "test", "tests"))
        else:
            shutil.copy2(item, lib_dst / item.name)

    sp_src = SRC_PY / "Lib" / "site-packages"
    sp_dst = lib_dst / "site-packages"
    sp_dst.mkdir()
    for item in sp_src.iterdir():
        if item.name in SKIP_SITE or item.name.startswith("__pycache__"):
            continue
        if item.is_dir():
            shutil.copytree(item, sp_dst / item.name, ignore=_ignore_site)
        else:
            shutil.copy2(item, sp_dst / item.name)

    # 打包版的 tkinter 需要 tcl/tk 数据（在 DLLs 与 Lib/tcl* 中，上面已复制）
    for junk in ("__pycache__",):
        for p in dst.rglob(junk):
            shutil.rmtree(p, ignore_errors=True)


def copy_app(dst: Path) -> None:
    app_dir = dst / "app"
    if app_dir.exists():
        shutil.rmtree(app_dir)
    app_dir.mkdir(parents=True)
    shutil.copytree(SRC_PKG, app_dir / "strainplot",
                    ignore=shutil.ignore_patterns("__pycache__", "*.pyc"))
    shutil.copy2(ROOT / "packaging" / "win" / "run_app.py", app_dir / "run_app.py")


def build_launcher(dst: Path) -> None:
    csc = Path(r"C:\Windows\Microsoft.NET\Framework64\v4.0.30319\csc.exe")
    if not csc.exists():
        csc = Path(r"C:\Windows\Microsoft.NET\Framework\v4.0.30319\csc.exe")
    if not csc.exists():
        print("! 找不到 csc.exe，跳过 exe 编译（可改用 build_windows_pyinstaller.bat）")
        return
    out = dst / f"{APP_NAME}.exe"
    cmd = [str(csc), "/nologo", "/target:winexe", "/optimize+",
           f"/out:{out}", f"/win32icon:{ROOT / 'packaging' / 'icon.ico'}",
           str(ROOT / "packaging" / "win" / "Launcher.cs")]
    subprocess.run(cmd, check=True, capture_output=True)
    print("exe ->", out, out.stat().st_size, "bytes")


def make_zip(dst: Path) -> Path:
    zip_path = DIST / f"StrainPlot-{VERSION}-win64.zip"
    if zip_path.exists():
        zip_path.unlink()
    with zipfile.ZipFile(zip_path, "w", zipfile.ZIP_DEFLATED, compresslevel=6) as zf:
        for p in sorted(dst.rglob("*")):
            if p.is_file():
                zf.write(p, Path(NAME) / p.relative_to(dst))
    return zip_path


def main() -> None:
    dst = DIST / NAME
    print("源解释器:", SRC_PY)
    print("复制 runtime ...")
    copy_runtime(dst / "runtime")
    print("复制 app ...")
    copy_app(dst)
    (dst / "README.txt").write_text(README, encoding="utf-8", newline="\r\n")
    print("编译启动器 ...")
    build_launcher(dst)

    total = sum(f.stat().st_size for f in dst.rglob("*") if f.is_file())
    print(f"目录大小: {total / 1048576:.1f} MB")
    z = make_zip(dst)
    print(f"zip: {z}  {z.stat().st_size / 1048576:.1f} MB")


if __name__ == "__main__":
    main()
