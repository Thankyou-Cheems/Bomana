@echo off
REM ============================================================================
REM Bomana lightweight smoke checks
REM ============================================================================
REM Runs the fast local regression suite only. Real 8111/game validation remains
REM a manual step for features that depend on War Thunder runtime data.
REM ============================================================================

setlocal

set "ROOT_DIR=%~dp0..\.."
pushd "%ROOT_DIR%" >nul
if %errorlevel% neq 0 (
    echo [error] cannot enter repository root: %ROOT_DIR%
    exit /b 1
)

set "UV_CMD=uv"
%UV_CMD% --version >nul 2>&1
if %errorlevel% neq 0 (
    set "UV_CMD=python -m uv"
    %UV_CMD% --version >nul 2>&1
    if %errorlevel% neq 0 (
        echo [error] uv is required: https://docs.astral.sh/uv/getting-started/installation/
        popd >nul
        exit /b 1
    )
)

echo [1/1] Running lightweight unittest smoke checks...
%UV_CMD% run python -m unittest discover -s tests -p "test_*.py"
if %errorlevel% neq 0 (
    echo [error] smoke checks failed
    popd >nul
    exit /b 1
)

echo Smoke checks passed.
popd >nul
exit /b 0
