@echo off
chcp 65001 > nul
title ESP32 烧录工具 - 打包为EXE

echo.
echo ========================================================
echo    ESP32 烧录工具 - 打包为EXE
echo ========================================================
echo.

REM 检查Python
python --version > nul 2>&1
if errorlevel 1 (
    echo [错误] 未检测到Python，请先安装Python 3.7+
    echo.
    pause
    exit /b 1
)

echo [步骤1] 检查并安装PyInstaller...
echo.
pip show pyinstaller > nul 2>&1
if errorlevel 1 (
    echo 正在安装 PyInstaller...
    pip install pyinstaller
    echo.
) else (
    echo PyInstaller 已安装 ✓
    echo.
)

echo [步骤2] 安装项目依赖（含最新 esptool）...
echo.
pip install -r requirements.txt
if errorlevel 1 (
    echo [错误] 依赖安装失败
    pause
    exit /b 1
)
python -c "import esptool; print('esptool', esptool.__version__)"
echo.

echo [步骤3] 清理旧的打包文件...
echo.
if exist "build" (
    rmdir /s /q build
    echo 已删除 build 目录
)
if exist "dist\esp32_flasher.exe" (
    del /q dist\esp32_flasher.exe
    echo 已删除旧的 exe 文件
)
echo.

echo [步骤4] 开始打包...
echo.
echo 打包选项：
echo   - 单文件模式（所有依赖打包到一个exe）
echo   - 包含窗口界面
echo   - 包含 tkinter、serial、esptool 等模块
echo.

REM 使用 build_exe.py 打包（含 Python 3.10.0 兼容性修复 + esptool 5.x 依赖）
python build_exe.py

if errorlevel 1 (
    echo.
    echo [错误] 打包失败！
    echo.
    pause
    exit /b 1
)

echo.
echo ========================================================
echo [成功] 打包完成！
echo ========================================================
echo.
echo 生成的文件位置：
echo   dist\esp32_flasher.exe
echo.

REM 检查文件大小
if exist "dist\esp32_flasher.exe" (
    echo 文件大小：
    for %%A in ("dist\esp32_flasher.exe") do (
        set size=%%~zA
        echo   %%~zA 字节 ^(约 %%~zA / 1024 / 1024 MB^)
    )
)
echo.
echo 提示：
echo   1. exe文件是独立的，可以直接运行
echo   2. 不需要安装Python
echo   3. 首次运行可能较慢（解压临时文件）
echo   4. 配置文件 config.json 会自动在exe同目录生成
echo   5. 可以将 exe 和 bin 固件文件一起打包分发
echo.
echo ========================================================
echo.

REM 询问是否测试运行
set /p test="是否立即测试运行？(Y/N): "
if /i "%test%"=="Y" (
    echo.
    echo 启动测试...
    start "" "dist\esp32_flasher.exe"
)

echo.
echo 按任意键退出...
pause > nul

