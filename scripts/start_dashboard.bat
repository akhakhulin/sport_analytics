@echo off
chcp 65001 >nul
cd /d "%~dp0\.."
set PYTHONIOENCODING=utf-8
for /f "tokens=2 delims==" %%I in ('wmic os get localdatetime /value ^| find "="') do set DT=%%I
set TS=%DT:~0,4%-%DT:~4,2%-%DT:~6,2%_%DT:~8,2%-%DT:~10,2%-%DT:~12,2%
echo === %TS% START dashboard === >> logs\dashboard.log
.venv\Scripts\python.exe -m streamlit run dashboard.py --server.headless=true --server.port=8501 --server.address=127.0.0.1 >> logs\dashboard.log 2>&1
echo === %TS% END dashboard (exit %ERRORLEVEL%) === >> logs\dashboard.log
