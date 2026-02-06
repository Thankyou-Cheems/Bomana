@echo off
REM 仅打包通用启动器（Bomana_launcher_vX.Y.Z.exe）
setlocal
set "VERSION=%~1"

if "%VERSION%"=="" (
  python tools\build_portable.py --target launcher
) else (
  python tools\build_portable.py --target launcher --version %VERSION%
)
endlocal
