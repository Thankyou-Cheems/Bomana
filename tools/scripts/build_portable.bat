@echo off
REM ============================================================================
REM Bomana 绿色版打包脚本 (Launcher + 可更新应用包)
REM ============================================================================
REM 用法:
REM   tools\scripts\build_portable.bat [Enhanced|Standard|Lite] [all|app|launcher] [version]
REM 示例:
REM   tools\scripts\build_portable.bat Enhanced
REM   tools\scripts\build_portable.bat Standard app 6.7.0
REM   tools\scripts\build_portable.bat Lite launcher
REM 说明:
REM   version 是一致性校验值，必须匹配源码中的 app 或 launcher 版本。
REM   target=launcher 时生成通用启动器（与 variant 无关）
REM   target=all 会构建当前 variant 的 app + 通用启动器；通常不要传单一 version。
REM ============================================================================

setlocal
set "EXIT_CODE=0"
set "ROOT_DIR=%~dp0..\.."
pushd "%ROOT_DIR%" >nul
if %errorlevel% neq 0 (
    echo [错误] 无法进入仓库根目录: %ROOT_DIR%
    endlocal & exit /b 1
)

set "VARIANT=%~1"
if "%VARIANT%"=="" set "VARIANT=Enhanced"
set "TARGET=%~2"
if "%TARGET%"=="" set "TARGET=all"
set "VERSION=%~3"

if /I not "%VARIANT%"=="Enhanced" if /I not "%VARIANT%"=="Standard" if /I not "%VARIANT%"=="Lite" (
    echo [错误] 版本类型无效: %VARIANT%
    echo 用法: tools\scripts\build_portable.bat Enhanced^|Standard^|Lite [all^|app^|launcher] [version]
    set "EXIT_CODE=1"
    goto :cleanup
)

if /I not "%TARGET%"=="all" if /I not "%TARGET%"=="app" if /I not "%TARGET%"=="launcher" (
    echo [错误] 打包目标无效: %TARGET%
    echo 用法: tools\scripts\build_portable.bat Enhanced^|Standard^|Lite [all^|app^|launcher] [version]
    set "EXIT_CODE=1"
    goto :cleanup
)

echo ========================================
echo Bomana 绿色版打包
echo ========================================
echo 版本类型: %VARIANT%
echo 打包目标: %TARGET%
if not "%VERSION%"=="" echo 版本号: %VERSION%
echo.

set "PYTHONPATH="
set "PYTHONHOME="
set "PYTHONNOUSERSITE=1"

set "UV_CMD=uv"
%UV_CMD% --version >nul 2>&1
if %errorlevel% neq 0 (
    set "UV_CMD=python -m uv"
    %UV_CMD% --version >nul 2>&1
    if %errorlevel% neq 0 (
        echo [错误] 未找到 uv，请先安装 uv: https://docs.astral.sh/uv/getting-started/installation/
        set "EXIT_CODE=1"
        goto :cleanup
    )
)

echo [信息] 同步依赖 (uv sync --extra build --frozen)...
%UV_CMD% sync --extra build --frozen
if %errorlevel% neq 0 (
    echo [错误] 依赖同步失败
    set "EXIT_CODE=1"
    goto :cleanup
)

if "%VERSION%"=="" (
    %UV_CMD% run --frozen python tools\build_portable.py --variant %VARIANT% --target %TARGET%
) else (
    %UV_CMD% run --frozen python tools\build_portable.py --variant %VARIANT% --target %TARGET% --version "%VERSION%"
)

if %errorlevel% neq 0 (
    echo.
    echo [错误] 打包失败
    set "EXIT_CODE=1"
    goto :cleanup
)

echo.
echo [成功] 绿色版打包完成，产物在 dist\ 目录
echo.

:cleanup
popd >nul
endlocal & exit /b %EXIT_CODE%
