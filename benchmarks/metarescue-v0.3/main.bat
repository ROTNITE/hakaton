@echo off
cd /d "%~dp0"
py -3 main.py
if errorlevel 1 (
    echo.
    echo If Python launcher is not installed, try: python main.py
    python main.py
)
pause
