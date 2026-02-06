@echo off
REM 仅打包可更新应用包（app.zip + manifest）
setlocal
set "VARIANT=%~1"
if "%VARIANT%"=="" set "VARIANT=Enhanced"
set "VERSION=%~2"

if "%VERSION%"=="" (
  call build_portable.bat %VARIANT% app
) else (
  call build_portable.bat %VARIANT% app %VERSION%
)
endlocal
