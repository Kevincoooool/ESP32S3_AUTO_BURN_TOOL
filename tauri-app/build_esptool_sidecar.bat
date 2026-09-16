@echo off
chcp 65001 > nul
title Build esptool sidecar for Tauri

echo.
echo ========================================================
echo    打包 esptool sidecar（随 Tauri exe 分发，无需 Python）
echo ========================================================
echo.

python --version > nul 2>&1
if errorlevel 1 (
    echo [错误] 未检测到 Python，打包 sidecar 需要 Python 3.7+
    pause
    exit /b 1
)

echo [1/3] 安装 esptool 与 PyInstaller...
pip install "esptool==5.3.1" pyinstaller>=6.0.0 -q
if errorlevel 1 (
    echo [错误] 依赖安装失败
    pause
    exit /b 1
)

echo [2/3] PyInstaller 打包 esptool...
python "%~dp0scripts\build_esptool_sidecar.py"
if errorlevel 1 (
    echo [错误] sidecar 打包失败
    pause
    exit /b 1
)

echo.
echo [3/3] 完成。sidecar 已写入 src-tauri\binaries\
echo       接下来可运行: npm run tauri build
echo.
if /i not "%~1"=="nopause" pause
