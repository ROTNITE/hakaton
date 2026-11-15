@echo off
chcp 65001 >nul
cd /d "%~dp0"
where py >nul 2>nul
if not errorlevel 1 (
    py -3 -B -X utf8 "%~dp0main.py" %*
) else (
    python -B -X utf8 "%~dp0main.py" %*
)
if errorlevel 1 (
    echo.
    echo Не удалось запустить. Установите Python 3.10+ и прочитайте README.md.
    pause
)
