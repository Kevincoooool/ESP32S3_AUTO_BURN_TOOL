@echo off
chcp 65001 >nul
echo ========================================
echo ESP32 自动烧录工具 - 打包脚本
echo ========================================
echo.

:: 检查 Python 是否安装
python --version >nul 2>&1
if %errorlevel% neq 0 (
    echo [错误] 未检测到 Python，请先安装 Python！
    echo 参考《用户使用指南.md》进行安装
    pause
    exit /b 1
)

echo [✓] Python 已安装
echo.

:: 检查 PyInstaller 是否安装
python -c "import PyInstaller" >nul 2>&1
if %errorlevel% neq 0 (
    echo [!] PyInstaller 未安装，正在自动安装...
    pip install pyinstaller>=6.0.0
    if %errorlevel% neq 0 (
        echo [错误] PyInstaller 安装失败！
        pause
        exit /b 1
    )
    echo [✓] PyInstaller 安装成功
    echo.
) else (
    echo [✓] PyInstaller 已安装
    echo.
)

:: 检查依赖是否安装
echo [!] 检查项目依赖...
python -c "import serial" >nul 2>&1
if %errorlevel% neq 0 (
    echo [!] 检测到缺少依赖，正在安装...
    pip install -r requirements.txt
    if %errorlevel% neq 0 (
        echo [错误] 依赖安装失败！
        pause
        exit /b 1
    )
)
echo [✓] 所有依赖已就绪
echo.

:: 清理旧的构建文件
if exist build (
    echo [!] 清理旧的构建文件...
    rmdir /s /q build
)
if exist dist (
    echo [!] 清理旧的可执行文件...
    rmdir /s /q dist
)
echo.

:: 打包 MAC 地址读取工具
echo ========================================
echo 正在打包 MAC 地址读取工具...
echo ========================================
pyinstaller esp32_readmac.spec
if %errorlevel% neq 0 (
    echo [错误] MAC 读取工具打包失败！
    pause
    exit /b 1
)
echo [✓] MAC 读取工具打包成功！
echo.

:: 打包固件烧录工具
echo ========================================
echo 正在打包固件烧录工具...
echo ========================================
pyinstaller esp32_flasher.spec
if %errorlevel% neq 0 (
    echo [错误] 固件烧录工具打包失败！
    pause
    exit /b 1
)
echo [✓] 固件烧录工具打包成功！
echo.

:: 显示结果
echo ========================================
echo 打包完成！
echo ========================================
echo.
echo 打包文件位置：
echo   - dist\esp32_readmac.exe  (MAC地址读取工具)
echo   - dist\esp32_flasher.exe  (固件烧录工具)
echo.
echo 文件大小：
dir dist\*.exe | find ".exe"
echo.

:: 询问是否打开 dist 文件夹
set /p open_folder="是否打开 dist 文件夹？(Y/N): "
if /i "%open_folder%"=="Y" (
    start explorer dist
)

echo.
echo 按任意键退出...
pause >nul
