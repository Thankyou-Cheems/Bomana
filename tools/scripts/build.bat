@echo off
REM ============================================================================
REM Bomana 打包脚本 (Windows)
REM ============================================================================
REM 
REM 使用说明：
REM 1. 确保已安装 uv
REM 2. 同步依赖: uv sync --extra build
REM 3. 运行此脚本（默认 Enhanced）：tools\scripts\build.bat
REM    或指定版本：tools\scripts\build.bat Enhanced|Standard|Lite
REM 
REM 输出文件将在 dist/ 目录下
REM ============================================================================

echo ========================================
echo Bomana 打包脚本
echo ========================================
echo.

set "ROOT_DIR=%~dp0..\.."
pushd "%ROOT_DIR%" >nul
if %errorlevel% neq 0 (
    echo [错误] 无法进入仓库根目录: %ROOT_DIR%
    pause
    exit /b 1
)

REM 检查 uv
echo [1/6] 检查 uv 环境...
set "UV_CMD=uv"
%UV_CMD% --version >nul 2>&1
if %errorlevel% neq 0 (
    set "UV_CMD=python -m uv"
    %UV_CMD% --version >nul 2>&1
    if %errorlevel% neq 0 (
        echo [错误] 未找到 uv，请先安装 uv: https://docs.astral.sh/uv/getting-started/installation/
        popd >nul
        pause
        exit /b 1
    )
)
%UV_CMD% --version
echo.

REM 检查依赖
echo [2/6] 检查依赖...
%UV_CMD% sync --extra build
if %errorlevel% neq 0 (
    echo [错误] 依赖同步失败
    popd >nul
    pause
    exit /b 1
)
echo 依赖同步完成
echo.

REM 解析版本类型
set "VARIANT=%~1"
if "%VARIANT%"=="" set "VARIANT=Enhanced"

if /I not "%VARIANT%"=="Enhanced" if /I not "%VARIANT%"=="Standard" if /I not "%VARIANT%"=="Lite" (
    echo [错误] 版本类型无效: %VARIANT%
    echo 用法: tools\scripts\build.bat Enhanced^|Standard^|Lite
    popd >nul
    pause
    exit /b 1
)
echo [3/6] 构建版本: %VARIANT%
echo.

if /I "%VARIANT%"=="Enhanced" (
    if not exist bomana\data\weapon_fire_control.json (
        echo [错误] Enhanced 缺少 bomana\data\weapon_fire_control.json
        popd >nul
        exit /b 1
    )
    if not exist docs\specs\schemas\weapon-fire-control.schema.json (
        echo [错误] Enhanced 缺少 docs\specs\schemas\weapon-fire-control.schema.json
        popd >nul
        exit /b 1
    )
)

REM 根据版本注入编译开关（备份后修改 feature_profile.py）
echo [4/6] 注入编译开关...
set "CONFIG_FILE=bomana\config\feature_profile.py"
set "CONFIG_BAK=bomana\config\feature_profile.py.bak"
if not exist "%CONFIG_FILE%" (
    echo [错误] 未找到 %CONFIG_FILE%
    popd >nul
    pause
    exit /b 1
)
copy /y "%CONFIG_FILE%" "%CONFIG_BAK%" >nul

if /I "%VARIANT%"=="Enhanced" (
    set "ENABLE_CCRP=True"
    set "ENABLE_ZONES=True"
    set "ENABLE_FUEL=True"
) else if /I "%VARIANT%"=="Standard" (
    set "ENABLE_CCRP=False"
    set "ENABLE_ZONES=True"
    set "ENABLE_FUEL=True"
) else (
    set "ENABLE_CCRP=False"
    set "ENABLE_ZONES=False"
    set "ENABLE_FUEL=False"
)
set "ENABLE_ADVANCED_SETTINGS=True"
set "ENABLE_AIRFIELDS=%ENABLE_ZONES%"
set "ENABLE_CHECKLIST=%ENABLE_ZONES%"

powershell -NoProfile -Command ^
  "$path = '%CONFIG_FILE%';" ^
  "$code = Get-Content $path -Raw;" ^
  "$switches = @{ 'ENABLE_CCRP' = '%ENABLE_CCRP%'; 'ENABLE_ZONES' = '%ENABLE_ZONES%'; 'ENABLE_AIRFIELDS' = '%ENABLE_AIRFIELDS%'; 'ENABLE_FUEL' = '%ENABLE_FUEL%'; 'ENABLE_CHECKLIST' = '%ENABLE_CHECKLIST%'; 'ENABLE_ADVANCED_SETTINGS' = '%ENABLE_ADVANCED_SETTINGS%' };" ^
  "foreach ($key in $switches.Keys) { $val = $switches[$key]; $code = $code -replace '(?m)^' + $key + '\s*=.*', ($key + ' = ' + $val); }" ^
  "$code | Set-Content $path -NoNewline"

REM 清理旧文件
echo [5/6] 清理旧的构建文件...
if exist build rmdir /s /q build
if exist dist rmdir /s /q dist
if exist Bomana.spec del Bomana.spec
echo 清理完成
echo.

REM 打包
echo [6/6] 开始打包...
echo 这可能需要几分钟时间，请耐心等待...
echo.

REM 生成版本信息文件
echo [5.5/6] 生成版本信息...
if exist file_version_info.txt del file_version_info.txt
%UV_CMD% run python tools\create_version_info.py --config bomana\metadata.py --output file_version_info.txt
if %errorlevel% neq 0 (
    if exist "%CONFIG_BAK%" move /y "%CONFIG_BAK%" "%CONFIG_FILE%" >nul
    echo [错误] 版本信息生成失败
    popd >nul
    pause
    exit /b 1
)
set "VERSION_ARG="
if exist file_version_info.txt (
    set "VERSION_ARG=--version-file file_version_info.txt"
) else (
    if exist "%CONFIG_BAK%" move /y "%CONFIG_BAK%" "%CONFIG_FILE%" >nul
    echo [错误] 未生成版本信息文件
    popd >nul
    pause
    exit /b 1
)


set "EXEC_NAME=Bomana_%VARIANT%"
set "CCRP_DATA_ARG="
set "WEAPON_DATA_ARG="
set "WEAPON_SCHEMA_ARG="
set "FM_SPEED_DATA_ARG="
if /I "%VARIANT%"=="Enhanced" (
    if exist bomana\data\ccrp_bomb_params.json (
        set "CCRP_DATA_ARG=--add-data \"bomana/data/ccrp_bomb_params.json;bomana/data\""
    ) else if exist ccrp_bomb_params.json (
        set "CCRP_DATA_ARG=--add-data \"ccrp_bomb_params.json;.\""
    ) else if exist ccrp_bomb_params.py (
        set "CCRP_DATA_ARG=--add-data \"ccrp_bomb_params.py;.\""
    )
    if exist bomana\data\weapon_fire_control.json (
        set "WEAPON_DATA_ARG=--add-data \"bomana/data/weapon_fire_control.json;bomana/data\""
    )
    if exist docs\specs\schemas\weapon-fire-control.schema.json (
        set "WEAPON_SCHEMA_ARG=--add-data \"docs/specs/schemas/weapon-fire-control.schema.json;docs/specs/schemas\""
    )
)
if exist bomana\data\fm_speed_limits.json (
    set "FM_SPEED_DATA_ARG=--add-data \"bomana/data/fm_speed_limits.json;bomana/data\""
)

if /I "%VARIANT%"=="Enhanced" (
    %UV_CMD% run pyinstaller --noconsole --onefile ^
                --name=%EXEC_NAME% ^
                --icon=bomana\assets\branding\app.ico ^
                --add-data "bomana/assets;bomana/assets" ^
                %CCRP_DATA_ARG% ^
                %WEAPON_DATA_ARG% ^
                %WEAPON_SCHEMA_ARG% ^
                %FM_SPEED_DATA_ARG% ^
                --hidden-import "pystray._win32" ^
                --collect-submodules "PIL" ^
                %VERSION_ARG% ^
                --clean Bomana.pyw
) else (
    %UV_CMD% run pyinstaller --noconsole --onefile ^
                --name=%EXEC_NAME% ^
                --icon=bomana\assets\branding\app.ico ^
                --add-data "bomana/assets;bomana/assets" ^
                %FM_SPEED_DATA_ARG% ^
                --hidden-import "pystray._win32" ^
                --collect-submodules "PIL" ^
                %VERSION_ARG% ^
                --clean Bomana.pyw
)

if %errorlevel% neq 0 (
    if exist "%CONFIG_BAK%" move /y "%CONFIG_BAK%" "%CONFIG_FILE%" >nul
    echo.
    echo [错误] 打包失败
    popd >nul
    pause
    exit /b 1
)

REM 恢复 feature_profile.py
if exist "%CONFIG_BAK%" move /y "%CONFIG_BAK%" "%CONFIG_FILE%" >nul

echo.
if exist file_version_info.txt del file_version_info.txt
echo [验证] 检查输出...
if exist "dist\%EXEC_NAME%.exe" (
    echo [成功] 打包完成！
    echo.
    echo 输出文件: dist\%EXEC_NAME%.exe
    echo.
    dir "dist\%EXEC_NAME%.exe"
    echo.
    echo ========================================
    echo 打包成功！
    echo ========================================
    echo.
    echo 你现在可以：
    echo 1. 运行 dist\%EXEC_NAME%.exe 测试程序
    echo 2. 将 dist\%EXEC_NAME%.exe 分发给其他用户
    echo.
) else (
    echo [错误] 未找到输出文件
    popd >nul
    pause
    exit /b 1
)

popd >nul
pause
