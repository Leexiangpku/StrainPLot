@echo off
rem ============================================================
rem  StrainPlot 一键启动脚本
rem  双击本文件即可打开图形界面。
rem ============================================================
chcp 65001 >nul
setlocal enabledelayedexpansion
cd /d "%~dp0"

rem ---- 1) 定位 Python ------------------------------------------------------
set "PY="
if exist "%~dp0python\pythonw.exe" set "PY=%~dp0python\pythonw.exe"
if not defined PY if exist "C:\Users\Administrator\.dsh\dsh-runtimes\dsh-primary-runtime\dependencies\python\pythonw.exe" (
    set "PY=C:\Users\Administrator\.dsh\dsh-runtimes\dsh-primary-runtime\dependencies\python\pythonw.exe"
)
if not defined PY (
    for /f "delims=" %%P in ('where pythonw.exe 2^>nul') do if not defined PY set "PY=%%P"
)
if not defined PY (
    for /f "delims=" %%P in ('where python.exe 2^>nul') do if not defined PY set "PY=%%P"
)

if not defined PY (
    echo.
    echo   [X] 未找到 Python。请先安装 Python 3.10 或更高版本。
    echo.
    pause
    exit /b 1
)

rem ---- 2) 依赖检查 ---------------------------------------------------------
set "PYC=%PY:pythonw.exe=python.exe%"
if not exist "%PYC%" set "PYC=%PY%"
"%PYC%" -c "import tkinter, PIL, numpy, openpyxl" >nul 2>nul
if errorlevel 1 (
    echo.
    echo   [X] 缺少依赖：tkinter / Pillow / numpy / openpyxl
    echo       请运行：  "%PYC%" -m pip install pillow numpy openpyxl
    echo.
    pause
    exit /b 1
)

rem ---- 3) 启动图形界面 -----------------------------------------------------
start "" "%PY%" -m strainplot
endlocal
exit /b 0
