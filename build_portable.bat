@echo off
REM ============================================================================
REM Bomana 绿色版打包脚本 (Launcher + 可更新应用包)
REM ============================================================================
REM 用法:
REM   build_portable.bat [Enhanced|Standard|Lite] [all|app|launcher] [version]
REM 示例:
REM   build_portable.bat Enhanced
REM   build_portable.bat Standard app 6.7.0
REM   build_portable.bat Lite launcher
REM 说明:
REM   target=launcher 时生成通用启动器（与 variant 无关）
REM ============================================================================

setlocal

set "VARIANT=%~1"
if "%VARIANT%"=="" set "VARIANT=Enhanced"
set "TARGET=%~2"
if "%TARGET%"=="" set "TARGET=all"
set "VERSION=%~3"

if /I not "%VARIANT%"=="Enhanced" if /I not "%VARIANT%"=="Standard" if /I not "%VARIANT%"=="Lite" (
    echo [错误] 版本类型无效: %VARIANT%
    echo 用法: build_portable.bat Enhanced^|Standard^|Lite [all^|app^|launcher] [version]
    exit /b 1
)

if /I not "%TARGET%"=="all" if /I not "%TARGET%"=="app" if /I not "%TARGET%"=="launcher" (
    echo [错误] 打包目标无效: %TARGET%
    echo 用法: build_portable.bat Enhanced^|Standard^|Lite [all^|app^|launcher] [version]
    exit /b 1
)

echo ========================================
echo Bomana 绿色版打包
echo ========================================
echo 版本类型: %VARIANT%
echo 打包目标: %TARGET%
if not "%VERSION%"=="" echo 版本号: %VERSION%
echo.

set "UV_CMD=uv"
%UV_CMD% --version >nul 2>&1
if %errorlevel% neq 0 (
    set "UV_CMD=python -m uv"
    %UV_CMD% --version >nul 2>&1
    if %errorlevel% neq 0 (
        echo [错误] 未找到 uv，请先安装 uv: https://docs.astral.sh/uv/getting-started/installation/
        exit /b 1
    )
)

echo [信息] 同步依赖 (uv sync --extra build)...
%UV_CMD% sync --extra build
if %errorlevel% neq 0 (
    echo [错误] 依赖同步失败
    exit /b 1
)

if "%VERSION%"=="" (
    %UV_CMD% run python tools\build_portable.py --variant %VARIANT% --target %TARGET%
) else (
    %UV_CMD% run python tools\build_portable.py --variant %VARIANT% --target %TARGET% --version %VERSION%
)

if %errorlevel% neq 0 (
    echo.
    echo [错误] 打包失败
    exit /b 1
)

echo.
echo [成功] 绿色版打包完成，产物在 dist\ 目录
echo.
endlocal
