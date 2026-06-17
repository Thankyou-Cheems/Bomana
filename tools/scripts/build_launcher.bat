@echo off
REM 仅打包通用启动器（Bomana_launcher_vX.Y.Z.exe）
REM 可选版本号必须匹配 launcher.pyw 中的 LAUNCHER_VERSION，否则构建会失败。
setlocal
set "EXIT_CODE=0"
set "ROOT_DIR=%~dp0..\.."
pushd "%ROOT_DIR%" >nul
if %errorlevel% neq 0 (
  echo [错误] 无法进入仓库根目录: %ROOT_DIR%
  endlocal & exit /b 1
)

set "VERSION=%~1"

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

%UV_CMD% sync --extra build
if %errorlevel% neq 0 (
  echo [错误] 依赖同步失败
  set "EXIT_CODE=1"
  goto :cleanup
)

if "%VERSION%"=="" (
  %UV_CMD% run python tools\build_portable.py --target launcher
) else (
  %UV_CMD% run python tools\build_portable.py --target launcher --version "%VERSION%"
)
if %errorlevel% neq 0 (
  set "EXIT_CODE=1"
)

:cleanup
popd >nul
endlocal & exit /b %EXIT_CODE%
