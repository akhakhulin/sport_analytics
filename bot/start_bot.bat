@echo off
REM Запуск Telegram-бота. Используется и из ярлыка, и из Task Scheduler.

cd /d "C:\1с_dev\garmin_analytics"

REM Активация venv (если есть)
if exist ".venv\Scripts\activate.bat" (
    call ".venv\Scripts\activate.bat"
)

REM Запуск бота. Stdout/stderr в logs/bot.log пишет уже само приложение.
python -m bot.main

REM Если запущено в обычном CMD (не Task Scheduler) — оставить окно для просмотра ошибки
if not "%TASKSCHEDULER%"=="1" (
    if errorlevel 1 (
        echo.
        echo Бот завершился с ошибкой. См. logs\bot.log
        pause
    )
)
