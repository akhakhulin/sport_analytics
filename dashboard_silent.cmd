@echo off
cd /d "%~dp0"
if not exist "data" mkdir "data"
start "" /B ".venv\Scripts\python.exe" -m streamlit run dashboard.py ^
  --server.headless=true ^
  --browser.gatherUsageStats=false ^
  --server.fileWatcherType=none ^
  --server.port=8501 ^
  > "data\dashboard.log" 2>&1
exit
