@echo off
setlocal enabledelayedexpansion
chcp 65001 > nul
title 清理编译产物

echo.
echo ========================================================
echo    ESP32 烧录工具 - 清理所有编译产物
echo ========================================================
echo.

set "ROOT=%~dp0"
set "APP=%ROOT%tauri-app"
set "N=0"

call :rm_dir "%APP%\node_modules" "前端依赖 node_modules"
call :rm_dir "%APP%\dist" "前端构建 dist"
call :rm_dir "%APP%\src-tauri\target" "Rust 编译 target"
call :rm_dir "%ROOT%build" "根目录 build"
call :rm_dir "%ROOT%dist" "根目录 dist"

echo.
if !N!==0 (
    echo 没有需要清理的编译产物。
) else (
    echo 共清理 !N! 项。
)
echo.
pause
exit /b 0

:rm_dir
if exist "%~1\" (
    echo [删除] %~2
    echo        %~1
    rd /s /q "%~1" 2>nul
    if exist "%~1\" (
        echo [失败] 无法删除: %~1
    ) else (
        set /a N+=1
    )
)
exit /b 0
