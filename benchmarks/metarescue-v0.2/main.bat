@echo off
chcp 65001 >nul
title MetaRescue Benchmark
cd /d "%~dp0"
where py >nul 2>&1
if %errorlevel%==0 (
  py -3 main.py
) else (
  python main.py
)
if errorlevel 1 (
  echo.
  echo Ошибка запуска. Проверьте README.md и установку Python.
  pause
)
