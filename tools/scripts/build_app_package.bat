@echo off
REM 仅打包可更新应用包（app.zip + manifest）
setlocal
set "EXIT_CODE=0"
set "ROOT_DIR=%~dp0..\.."
pushd "%ROOT_DIR%" >nul
if %errorlevel% neq 0 (
  echo [错误] 无法进入仓库根目录: %ROOT_DIR%
  endlocal & exit /b 1
)

set "VARIANT=%~1"
if "%VARIANT%"=="" set "VARIANT=Standard"
set "VERSION=%~2"

if "%VERSION%"=="" (
  call "%~dp0build_portable.bat" %VARIANT% app
) else (
  call "%~dp0build_portable.bat" %VARIANT% app %VERSION%
)
set "EXIT_CODE=%errorlevel%"
popd >nul
endlocal & exit /b %EXIT_CODE%
