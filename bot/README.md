# Telegram-агент тренировок

Бот @RoadToMC_bot для атлета.

## Что делает

1. **Утром при включении ПК** — синкает Garmin (sleep, RHR, HRV) → проверяет план на сегодня → присылает отчёт в Telegram
2. **Каждые 30 минут** — проверяет новые активности → анализирует время в плановой HR-зоне → присылает отчёт
3. **Команды** в Telegram:
   - `/today` — план на сегодня + утренние данные сейчас
   - `/last` — последняя записанная тренировка + анализ зон
   - `/week` — план текущей недели
   - `/check` — принудительно дёрнуть Garmin sync и проверить новые активности
   - `/help` — справка

## Архитектура

- Локальный Windows-процесс (через `start_bot.bat`)
- Long-polling Telegram (бот всегда онлайн пока ПК работает)
- APScheduler внутри telegram-bot — задачи на расписании
- Хранение состояния в существующей `data/garmin.db` (новые таблицы `bot_state`, `bot_messages`, `training_assessment`)
- Источник плана — `plans/2026_05_may_schedule_v2.xlsx`, лист «Тренировки списком»

## Файлы

```
bot/
├── main.py              # entry point: python -m bot.main
├── config.py            # env loading + paths
├── db.py                # bot tables + helpers
├── plan_reader.py       # парсер Excel плана
├── garmin_client.py     # Garmin Connect клиент
├── analyzer.py          # анализ time-in-zones
├── morning.py           # утренний регламент
├── activity_check.py    # post-workout анализ
├── handlers.py          # /команды
├── scheduler.py         # APScheduler tasks
├── start_bot.bat        # autostart wrapper
└── README.md
```

## Запуск

### Первый запуск (привязка)

1. Получить токен через @BotFather и положить в `.env`:
   ```
   TELEGRAM_BOT_TOKEN=...
   ```
2. Запустить бота:
   ```bash
   python -m bot.main
   ```
3. В Telegram найти бота и отправить `/start` — бот сохранит `chat_id` в `bot_state`.

### Постоянная работа (Windows Task Scheduler)

Регистрируется один раз. Не зависит от ярлыков, нельзя случайно удалить из Проводника, перезапускается при падении (5 попыток, интервал 1 мин).

```powershell
# Установка (из корня проекта C:\1с_dev\garmin_analytics):
PowerShell -ExecutionPolicy Bypass -File bot\install_autostart.ps1

# Удаление:
PowerShell -ExecutionPolicy Bypass -File bot\uninstall_autostart.ps1

# Запустить прямо сейчас (не дожидаясь логина):
Start-ScheduledTask -TaskName GarminBot

# Остановить:
Stop-ScheduledTask -TaskName GarminBot

# Посмотреть в GUI:
taskschd.msc  → Task Scheduler Library → GarminBot
```

При следующем логине Windows бот стартует автоматически в скрытом окне.

### Защита от двойного запуска

При старте бот пишет PID в `logs/bot.lock`. Второй запуск проверит файл и откажется, если первый процесс жив. Это защищает от ситуации «дважды кликнул start_bot.bat → 2 экземпляра конфликтуют по polling Telegram».

### Проверка что бот жив

В Telegram отправь `/status` — увидишь PID, последний heartbeat (обновляется раз в минуту), статус Garmin-клиента, и расписание.

## Настройки

Все настройки в `bot/config.py`:
- `ACTIVITY_POLL_INTERVAL_MIN` — интервал polling (default 30 мин)
- `MORNING_HOUR_RANGE` — окно для утреннего отчёта (default 06:00–11:00)
- `ZONE_COMPLIANCE_THRESHOLD` — порог соответствия плану (default 0.70 = 70%)

## Требования

- Python 3.11+
- Зависимости: `python-telegram-bot[job-queue]`, `APScheduler`, `openpyxl`, `garminconnect` (установлены ранее по проекту)

## Логи

`logs/bot.log` (ротация на твоё усмотрение).

## Безопасность

- Токен Telegram в `.env` (gitignored)
- `chat_id` после первого `/start` сохраняется в БД и блокирует чужих
- Garmin кредишены — те же что использует `garmin_sync.py`
