@echo off
REM 仅打包通用启动器（Bomana_launcher_vX.Y.Z.exe）
setlocal
set "VERSION=%~1"

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

%UV_CMD% sync --extra build
if %errorlevel% neq 0 (
  echo [错误] 依赖同步失败
  exit /b 1
)

if "%VERSION%"=="" (
  %UV_CMD% run python tools\build_portable.py --target launcher
) else (
  %UV_CMD% run python tools\build_portable.py --target launcher --version %VERSION%
)
endlocal
