@echo off
setlocal DisableDelayedExpansion
"%~dp0runtime\python\python.exe" -I -B "%~dp0workspace\verify_installation.py" --app-root "%~dp0."
pause
