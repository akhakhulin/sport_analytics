@echo off
chcp 65001 >nul
cd /d "%~dp0\.."
set PYTHONIOENCODING=utf-8
for /f "tokens=2 delims==" %%I in ('wmic os get localdatetime /value ^| find "="') do set DT=%%I
set TS=%DT:~0,4%-%DT:~4,2%-%DT:~6,2%_%DT:~8,2%-%DT:~10,2%-%DT:~12,2%
echo === %TS% sync_worker start === >> logs\sync_worker.log
.venv\Scripts\python.exe -u -m signup_service.sync_worker >> logs\sync_worker.log 2>&1
echo === %TS% sync_worker exit %ERRORLEVEL% === >> logs\sync_worker.log
