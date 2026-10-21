# -*- mode: python ; coding: utf-8 -*-
"""PyInstaller 打包配置：生成自带 Python / Tk 运行时的 StrainPlot.app。

用法（由 packaging/macos/build_macos.sh 调用）：

    PYINSTALLER_CONFIG_DIR=.build/pyi-config \
        .build/venv/bin/pyinstaller --noconfirm --clean \
        --distpath dist --workpath .build/pyi packaging/macos/StrainPlot.spec
"""

import os

ROOT = os.path.abspath(os.path.join(SPECPATH, "..", ".."))
SRC = ROOT                                     # strainplot/ 就在仓库根目录
ICON = os.path.join(ROOT, "packaging", "icon.icns")

VERSION = "0.20"
try:                                           # 版本号只有一个来源：strainplot/__init__.py
    _ns: dict = {}
    with open(os.path.join(SRC, "strainplot", "__init__.py"), encoding="utf-8") as fh:
        exec(compile(fh.read(), "__init__.py", "exec"), _ns)
    VERSION = _ns.get("__version__", VERSION)
except Exception:
    pass

a = Analysis(
    [os.path.join(SPECPATH, "entry.py")],
    pathex=[SRC],
    binaries=[],
    datas=[],
    hiddenimports=["PIL._tkinter_finder"],
    hookspath=[],
    runtime_hooks=[],
    excludes=["pytest", "setuptools", "pip"],
    noarchive=False,
)
pyz = PYZ(a.pure)

exe = EXE(
    pyz,
    a.scripts,
    [],
    exclude_binaries=True,
    name="StrainPlot",
    debug=False,
    strip=False,
    upx=False,
    console=False,
    disable_windowed_traceback=False,
    argv_emulation=False,
    target_arch=None,
    codesign_identity=None,
    entitlements_file=None,
)

coll = COLLECT(
    exe,
    a.binaries,
    a.datas,
    strip=False,
    upx=False,
    name="StrainPlot",
)

app = BUNDLE(
    coll,
    name="StrainPlot.app",
    icon=ICON,
    bundle_identifier="com.strainplot.app",
    version=VERSION,
    info_plist={
        "CFBundleName": "StrainPlot",
        "CFBundleDisplayName": "StrainPlot",
        "CFBundleShortVersionString": VERSION,
        "CFBundleVersion": VERSION,
        "LSMinimumSystemVersion": "11.0",
        "NSHighResolutionCapable": True,
        "NSRequiresAquaSystemAppearance": False,
        "NSHumanReadableCopyright": "StrainPlot",
    },
)
