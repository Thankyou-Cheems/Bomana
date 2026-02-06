@echo off
REM ============================================================================
REM Bomana 打包脚本 (Windows)
REM ============================================================================
REM 
REM 使用说明：
REM 1. 确保已安装 Python 3.8+
REM 2. 确保已安装依赖: pip install -r requirements.txt
REM 3. 运行此脚本（默认 Enhanced）：build.bat
REM    或指定版本：build.bat Enhanced|Standard|Lite
REM 
REM 输出文件将在 dist/ 目录下
REM ============================================================================

echo ========================================
echo Bomana 打包脚本
echo ========================================
echo.

REM 检查 Python
echo [1/6] 检查 Python 环境...
python --version >nul 2>&1
if %errorlevel% neq 0 (
    echo [错误] 未找到 Python，请先安装 Python 3.8+
    pause
    exit /b 1
)
python --version
echo.

REM 检查依赖
echo [2/6] 检查依赖...
pip show pyinstaller >nul 2>&1
if %errorlevel% neq 0 (
    echo [警告] 未安装 PyInstaller，正在安装...
    pip install pyinstaller
    if %errorlevel% neq 0 (
        echo [错误] PyInstaller 安装失败
        pause
        exit /b 1
    )
)
echo PyInstaller 已安装
echo.

REM 解析版本类型
set "VARIANT=%~1"
if "%VARIANT%"=="" set "VARIANT=Enhanced"

if /I not "%VARIANT%"=="Enhanced" if /I not "%VARIANT%"=="Standard" if /I not "%VARIANT%"=="Lite" (
    echo [错误] 版本类型无效: %VARIANT%
    echo 用法: build.bat Enhanced^|Standard^|Lite
    pause
    exit /b 1
)
echo [3/6] 构建版本: %VARIANT%
echo.

REM 根据版本注入编译开关（备份后修改 config.py）
echo [4/6] 注入编译开关...
set "CONFIG_FILE=bomana\config.py"
set "CONFIG_BAK=bomana\config.py.bak"
if not exist "%CONFIG_FILE%" (
    echo [错误] 未找到 %CONFIG_FILE%
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
python tools\create_version_info.py --config bomana\config.py --output file_version_info.txt
set "VERSION_ARG="
if exist file_version_info.txt (
    set "VERSION_ARG=--version-file file_version_info.txt"
)


set "EXEC_NAME=Bomana_%VARIANT%"
set "CCRP_DATA_ARG="
if /I "%VARIANT%"=="Enhanced" (
    if exist ccrp_bomb_params.json (
        set "CCRP_DATA_ARG=--add-data \"ccrp_bomb_params.json;.\""
    ) else if exist ccrp_bomb_params.py (
        set "CCRP_DATA_ARG=--add-data \"ccrp_bomb_params.py;.\""
    )
)

if /I "%VARIANT%"=="Enhanced" if not "%CCRP_DATA_ARG%"=="" (
    pyinstaller --noconsole --onefile ^
                --name=%EXEC_NAME% ^
                --icon=app.ico ^
                --add-data "app.png;." ^
                --add-data "sponsor_wechat.png;." ^
                %CCRP_DATA_ARG% ^
                --hidden-import "pystray._win32" ^
                --collect-submodules "PIL" ^
                %VERSION_ARG% ^
                --clean Bomana.pyw
) else (
    pyinstaller --noconsole --onefile ^
                --name=%EXEC_NAME% ^
                --icon=app.ico ^
                --add-data "app.png;." ^
                --add-data "sponsor_wechat.png;." ^
                --hidden-import "pystray._win32" ^
                --collect-submodules "PIL" ^
                %VERSION_ARG% ^
                --clean Bomana.pyw
)

if %errorlevel% neq 0 (
    if exist "%CONFIG_BAK%" move /y "%CONFIG_BAK%" "%CONFIG_FILE%" >nul
    echo.
    echo [错误] 打包失败
    pause
    exit /b 1
)

REM 恢复 config.py
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
    pause
    exit /b 1
)

pause
