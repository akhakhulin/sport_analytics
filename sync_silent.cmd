@echo off
cd /d "%~dp0"
".venv\Scripts\python.exe" garmin_sync.py >> "data\sync.log" 2>&1
