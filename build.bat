@echo off
REM ============================================================================
REM Bomana 打包脚本 (Windows)
REM ============================================================================
REM 
REM 使用说明：
REM 1. 确保已安装 Python 3.7+
REM 2. 确保已安装依赖: pip install -r requirements.txt
REM 3. 双击运行此脚本，或在命令行执行: build.bat
REM 
REM 输出文件将在 dist/ 目录下
REM ============================================================================

echo ========================================
echo Bomana 打包脚本
echo ========================================
echo.

REM 检查 Python
echo [1/5] 检查 Python 环境...
python --version >nul 2>&1
if %errorlevel% neq 0 (
    echo [错误] 未找到 Python，请先安装 Python 3.7+
    pause
    exit /b 1
)
python --version
echo.

REM 检查依赖
echo [2/5] 检查依赖...
pip show pyinstaller >nul 2>&1
if %errorlevel% neq 0 (
    echo [警告] 未安装 PyInstaller，正在安装...
    pip install pyinstaller
    if %errorlevel% neq 0 (
        echo [错误] PyInstaller 安装失败
        pause
        exit /b 1
    )
)
echo PyInstaller 已安装
echo.

REM 清理旧文件
echo [3/5] 清理旧的构建文件...
if exist build rmdir /s /q build
if exist dist rmdir /s /q dist
if exist Bomana.spec del Bomana.spec
echo 清理完成
echo.

REM 打包
echo [4/5] 开始打包...
echo 这可能需要几分钟时间，请耐心等待...
echo.

pyinstaller --onefile ^
            --windowed ^
            --icon=app.ico ^
            --name=Bomana ^
            --add-data "app.png;." ^
            --add-data "sponsor_wechat.png;." ^
            Bomana.pyw

if %errorlevel% neq 0 (
    echo.
    echo [错误] 打包失败
    pause
    exit /b 1
)

echo.
echo [5/5] 验证输出...
if exist "dist\Bomana.exe" (
    echo [成功] 打包完成！
    echo.
    echo 输出文件: dist\Bomana.exe
    echo.
    dir "dist\Bomana.exe"
    echo.
    echo ========================================
    echo 打包成功！
    echo ========================================
    echo.
    echo 你现在可以：
    echo 1. 运行 dist\Bomana.exe 测试程序
    echo 2. 将 dist\Bomana.exe 分发给其他用户
    echo.
) else (
    echo [错误] 未找到输出文件
    pause
    exit /b 1
)

pause
