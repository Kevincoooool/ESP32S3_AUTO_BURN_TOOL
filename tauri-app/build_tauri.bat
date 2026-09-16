@echo off
chcp 65001 > nul
title ESP32 烧录工具 Tauri 完整打包

echo.
echo ========================================================
echo    ESP32 烧录工具 (Tauri) - 完整打包
echo    Rust 原生 espflash，对齐 esptool 5.x 协议
echo    单 exe 分发，无需 Python / sidecar
echo ========================================================
echo.

cd /d "%~dp0"

if exist "%USERPROFILE%\.cargo\bin" (
    set "PATH=%USERPROFILE%\.cargo\bin;%PATH%"
)

where cargo >nul 2>&1
if errorlevel 1 (
    echo [错误] 未找到 cargo，请先安装 Rust: https://rustup.rs
    pause
    exit /b 1
)

where npm >nul 2>&1
if errorlevel 1 (
    echo [错误] 未找到 npm，请先安装 Node.js
    pause
    exit /b 1
)

if not exist "node_modules\" (
    echo [1/2] 安装前端依赖...
    call npm install
    if errorlevel 1 (
        echo [错误] npm install 失败
        pause
        exit /b 1
    )
) else (
    echo [1/2] 前端依赖已就绪
)

echo.
echo [2/2] Tauri 打包...
call npm run tauri:build
if errorlevel 1 (
    echo [错误] Tauri 打包失败
    pause
    exit /b 1
)

echo.
echo ========================================================
echo 完成！安装包位于:
echo   src-tauri\target\release\bundle\nsis\
echo.
echo 分发给他人: 发送 setup.exe 即可，无需 esptool.exe
echo ========================================================
echo.
pause
