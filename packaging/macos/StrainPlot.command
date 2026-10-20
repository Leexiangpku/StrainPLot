#!/bin/bash
# StrainPlot macOS 启动器：双击运行（首次会自动准备 Python 环境）
# 依赖联网一次（pip 安装 pillow / numpy / openpyxl），之后离线可用。

cd "$(dirname "$0")" || exit 1
APP_DIR="$(pwd)"
VENV="$HOME/Library/Application Support/StrainPlot/venv"
PY="$VENV/bin/python"

echo "StrainPlot · 拉伸曲线一键处理与科研绘图"
echo "----------------------------------------"

find_python() {
  for c in python3.12 python3.11 python3.10 python3.9 python3; do
    if command -v "$c" >/dev/null 2>&1; then
      if "$c" -c 'import sys; sys.exit(0 if sys.version_info >= (3, 9) else 1)' 2>/dev/null; then
        echo "$c"
        return 0
      fi
    fi
  done
  return 1
}

if [ ! -x "$PY" ]; then
  BASE_PY="$(find_python)"
  if [ -z "$BASE_PY" ]; then
    echo "未找到 Python 3.9+。请先安装 Python："
    echo "  https://www.python.org/downloads/macos/   （推荐 3.12）"
    echo
    read -r -p "按回车关闭窗口..."
    exit 1
  fi
  echo "首次运行：正在创建独立环境（$BASE_PY）..."
  mkdir -p "$(dirname "$VENV")"
  "$BASE_PY" -m venv "$VENV" || {
    echo "创建虚拟环境失败，请检查 $BASE_PY 是否为完整安装。"
    read -r -p "按回车关闭窗口..."
    exit 1
  }
  "$PY" -m pip install --upgrade pip >/dev/null 2>&1
  echo "正在安装依赖 pillow / numpy / openpyxl ..."
  if ! "$PY" -m pip install pillow numpy openpyxl; then
    echo
    echo "依赖安装失败（可能是网络问题）。可手动执行："
    echo "  \"$PY\" -m pip install pillow numpy openpyxl"
    read -r -p "按回车关闭窗口..."
    exit 1
  fi
fi

# Tkinter 是系统 Python 自带的；若缺失给出提示
if ! "$PY" -c 'import tkinter' 2>/dev/null; then
  echo "当前 Python 缺少 tkinter（Homebrew 版需要：brew install python-tk@3.12）。"
  read -r -p "按回车关闭窗口..."
  exit 1
fi

PYTHONPATH="$APP_DIR${PYTHONPATH:+:$PYTHONPATH}" "$PY" -m strainplot
status=$?
if [ $status -ne 0 ]; then
  echo
  echo "程序退出，状态码 $status。"
  read -r -p "按回车关闭窗口..."
fi
