@echo off
setlocal

set "ROOT_DIR=%~dp0..\.."
pushd "%ROOT_DIR%" >nul
if errorlevel 1 (
    echo [错误] 无法进入仓库根目录
    exit /b 1
)

set "VARIANT=%~1"
if "%VARIANT%"=="" set "VARIANT=Enhanced"
if /I not "%VARIANT%"=="Enhanced" if /I not "%VARIANT%"=="Standard" if /I not "%VARIANT%"=="Lite" (
    echo [错误] 版本类型无效: %VARIANT%
    popd >nul
    exit /b 1
)

where uv >nul 2>&1
if errorlevel 1 (
    echo [错误] 未找到 uv
    popd >nul
    exit /b 1
)

uv sync --extra build --frozen
if errorlevel 1 (
    popd >nul
    exit /b 1
)

uv run --frozen python tools\build_portable.py ^
    --variant "%VARIANT%" ^
    --target app ^
    --output dist
set "BUILD_EXIT=%ERRORLEVEL%"
popd >nul
exit /b %BUILD_EXIT%
