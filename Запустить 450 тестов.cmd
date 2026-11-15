@echo off
powershell.exe -NoProfile -ExecutionPolicy Bypass -File "%~dp0tools\start_overnight_series.ps1"
echo.
echo Press any key to close this window.
pause >nul
