@echo off
REM Сборка sync.exe для рассылки атлетам.
REM
REM Требования (один раз):
REM   .venv\Scripts\activate.bat
REM   pip install pyinstaller
REM
REM После сборки готовый файл: dist\sync.exe (~70-100 MB)
REM Атлету нужно прислать: sync.exe + .env.example (как шаблон конфига).

cd /d "%~dp0"
call .venv\Scripts\activate.bat

REM Чистим прошлые артефакты, чтобы PyInstaller не подтащил кэш
rmdir /s /q build 2>nul
rmdir /s /q dist 2>nul

pyinstaller --clean --noconfirm garmin_sync.spec

if errorlevel 1 (
    echo.
    echo [BUILD FAILED] Смотри сообщение PyInstaller выше.
    pause
    exit /b 1
)

echo.
echo ============================================================
echo  Сборка готова: dist\sync.exe
echo ============================================================
echo  Размер:
for %%I in (dist\sync.exe) do echo    %%~zI байт
echo.
echo  Что отправлять атлету:
echo    1. dist\sync.exe
echo    2. .env.example  (атлет переименует в .env, заполнит)
echo ============================================================
pause
