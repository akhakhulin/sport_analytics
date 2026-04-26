@echo off
chcp 65001 >nul
REM ============================================================
REM Создаёт две задачи в Windows Task Scheduler:
REM   1) GarminSync_Daily  — каждый день в 12:00 (днём комп чаще включён)
REM   2) GarminSync_Logon  — при каждом входе в Windows
REM
REM Несколько триггеров → ловим любую возможность, когда PC включён.
REM Запуск sync.exe инкрементальный, так что несколько раз подряд — это
REM ноль трафика после первой свежей выгрузки.
REM
REM Запустить ОДИН РАЗ, двойным кликом.
REM ============================================================

cd /d "%~dp0"
set "VBS=%~dp0sync_silent.vbs"
set "EXE=%~dp0sync.exe"

if not exist "%EXE%" (
    echo [ОШИБКА] sync.exe не найден рядом с этим файлом.
    echo          Положи install_schedule.cmd в одну папку с sync.exe и запусти заново.
    pause
    exit /b 1
)

if not exist "%VBS%" (
    echo [ОШИБКА] sync_silent.vbs не найден рядом с этим файлом.
    pause
    exit /b 1
)

REM Удаляем старые задачи с теми же именами (если были)
schtasks /delete /tn "GarminSync"        /f >nul 2>&1
schtasks /delete /tn "GarminSync_Daily"  /f >nul 2>&1
schtasks /delete /tn "GarminSync_Logon"  /f >nul 2>&1

REM Триггер 1 — ежедневно в 12:00
schtasks /create ^
    /tn "GarminSync_Daily" ^
    /tr "wscript.exe \"%VBS%\"" ^
    /sc DAILY ^
    /st 12:00 ^
    /rl LIMITED ^
    /f
if errorlevel 1 goto :err

REM Триггер 2 — при входе пользователя в Windows
schtasks /create ^
    /tn "GarminSync_Logon" ^
    /tr "wscript.exe \"%VBS%\"" ^
    /sc ONLOGON ^
    /rl LIMITED ^
    /f
if errorlevel 1 goto :err

echo.
echo ============================================================
echo  Готово. Создано две задачи:
echo    GarminSync_Daily  — каждый день в 12:00
echo    GarminSync_Logon  — при каждом входе в Windows
echo  Все запуски скрытые, без всплывающих окон.
echo  Логи:   data\sync.log
echo.
echo  Проверить прямо сейчас:
echo      schtasks /run /tn "GarminSync_Logon"
echo.
echo  Удалить автозапуск:
echo      двойной клик по uninstall_schedule.cmd
echo ============================================================
pause
exit /b 0

:err
echo.
echo [ОШИБКА] Не получилось создать задачу.
echo Попробуй запустить файл «От имени администратора» (правый клик).
pause
exit /b 1
