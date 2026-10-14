@echo off
setlocal DisableDelayedExpansion
"%~dp0runtime\python\python.exe" -I "%~dp0workspace\verify_installation.py" --app-root "%~dp0."
set "workbench_exit=%errorlevel%"
echo.
pause
exit /b %workbench_exit%
