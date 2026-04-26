@echo off
chcp 65001 >nul
REM Удаляет задачи GarminSync_* из Windows Task Scheduler.
REM Сами файлы (sync.exe, .env, data\) не трогает.

set "REMOVED=0"

for %%T in (GarminSync GarminSync_Daily GarminSync_Logon) do (
    schtasks /delete /tn "%%T" /f >nul 2>&1
    if not errorlevel 1 (
        echo Удалена: %%T
        set /a REMOVED+=1
    )
)

if %REMOVED%==0 (
    echo.
    echo Задачи GarminSync_* не найдены ^(возможно, уже удалены^).
) else (
    echo.
    echo Автозапуск выключен. Удалено задач: %REMOVED%
)
echo.
pause
