@echo off
setlocal
REM Build WinUI3 frontend and export runtime files to winui\dist

set CONFIG=%1
if "%CONFIG%"=="" set CONFIG=Release

set PLATFORM=%2
if "%PLATFORM%"=="" set PLATFORM=x64

python tools\build_winui_frontend.py --configuration %CONFIG% --platform %PLATFORM%
