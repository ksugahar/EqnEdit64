@echo off
setlocal
cd /d "%~dp0.."
if not exist "build\EqnEdit64.exe" (
    echo [ERROR] build\EqnEdit64.exe is missing. Run build_eqnedit64.bat first.
    pause
    exit /b 1
)
start "" "build\EqnEdit64.exe" --debug-operations
