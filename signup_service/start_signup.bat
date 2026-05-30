@echo off
chcp 65001 >nul
cd /d "%~dp0\.."
echo === %DATE% %TIME% signup-service start === >> logs\signup_bat.log

set PYTHONIOENCODING=utf-8
REM В проде задать BEATMETRICS_SESSION_SECRET через GUI Task Scheduler / переменные окружения
REM и BEATMETRICS_COOKIE_SECURE=1 после установки TLS

.venv\Scripts\python.exe -u -m uvicorn signup_service.main:app ^
    --host 127.0.0.1 --port 8502 --log-level info ^
    >> logs\signup_bat.log 2>&1

echo === %DATE% %TIME% signup-service exit %ERRORLEVEL% === >> logs\signup_bat.log
