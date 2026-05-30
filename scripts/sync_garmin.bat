@echo off
cd /d "%~dp0\.."
rem TS считаем ДО chcp 65001: под UTF-8-кодовой страницей for /f часто ловит пустой захват вывода
for /f %%I in ('powershell -NoProfile -Command "Get-Date -Format yyyy-MM-dd_HH-mm-ss"') do set "TS=%%I"
chcp 65001 >nul
set GARMIN_TOKENS_DIR=./garminconnect
set PYTHONIOENCODING=utf-8
echo === %TS% START === >> logs\sync.log
.venv\Scripts\python.exe garmin_sync.py >> logs\sync.log 2>&1
echo === %TS% END (exit %ERRORLEVEL%) === >> logs\sync.log
exit /b %ERRORLEVEL%
