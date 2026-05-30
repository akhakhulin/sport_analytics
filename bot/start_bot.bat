@echo off
chcp 65001 >nul
cd /d "%~dp0\.."
echo === %DATE% %TIME% bat start, cwd=%CD% === >> logs\bot_bat.log

set PYTHONIOENCODING=utf-8
set SSL_CERT_FILE=%CD%\.venv\Lib\site-packages\certifi\cacert.pem
set REQUESTS_CA_BUNDLE=%CD%\.venv\Lib\site-packages\certifi\cacert.pem
set GARMIN_TOKENS_DIR=./garminconnect

if exist ".venv\Scripts\activate.bat" call ".venv\Scripts\activate.bat"

.venv\Scripts\python.exe -m bot.main >> logs\bot_bat.log 2>&1
echo === %DATE% %TIME% bat exit %ERRORLEVEL% === >> logs\bot_bat.log
