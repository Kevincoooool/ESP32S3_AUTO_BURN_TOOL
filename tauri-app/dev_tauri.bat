@echo off
chcp 65001 > nul
title ESP32 烧录工具 Tauri 开发模式

cd /d "%~dp0"

if exist "%USERPROFILE%\.cargo\bin" (
    set "PATH=%USERPROFILE%\.cargo\bin;%PATH%"
)

where cargo >nul 2>&1
if errorlevel 1 (
    echo [错误] 未找到 cargo，请先安装 Rust: https://rustup.rs
    echo 或确认 %USERPROFILE%\.cargo\bin 存在
    pause
    exit /b 1
)

echo 使用 cargo: 
cargo --version
echo.
echo 启动 Tauri 开发模式...
call npm run tauri dev
