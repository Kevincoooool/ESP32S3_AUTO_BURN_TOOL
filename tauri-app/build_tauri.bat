@echo off
chcp 65001 > nul
title ESP32 烧录工具 Tauri 完整打包

echo.
echo ========================================================
echo    ESP32 烧录工具 (Tauri) - 完整打包
echo    内置 esptool 5.3 sidecar，无需 Python
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

echo [1/2] 打包 esptool sidecar...
call "%~dp0build_esptool_sidecar.bat" nopaause
if errorlevel 1 (
    echo [错误] esptool sidecar 打包失败
    pause
    exit /b 1
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
echo   src-tauri\target\release\bundle\
echo ========================================================
echo.
pause
