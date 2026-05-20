"""Точка входа бота — запускать через `python -m bot.main` или start_bot.bat."""
from __future__ import annotations

import atexit
import logging
import os
import sys
from pathlib import Path

from telegram.error import NetworkError, TimedOut
from telegram.ext import (
    Application,
    CallbackQueryHandler,
    CommandHandler,
    ContextTypes,
    MessageHandler,
    filters,
)
from telegram.request import HTTPXRequest

from . import config, db, garmin_client, handlers, scheduler

LOCK_FILE = config.PROJECT_ROOT / "logs" / "bot.lock"


def acquire_single_instance_lock() -> None:
    """Атомарная защита от двух экземпляров.

    Использует O_CREAT|O_EXCL чтобы операция «создать lock если его нет»
    была атомарной — два процесса не могут одновременно «успеть» захватить.
    Если файл уже есть — проверяем PID, если мёртв — стираем и пробуем снова.
    """
    LOCK_FILE.parent.mkdir(parents=True, exist_ok=True)
    pid_str = str(os.getpid()).encode("utf-8")

    for attempt in range(2):
        try:
            # Атомарно создать новый файл; если существует — будет FileExistsError
            fd = os.open(str(LOCK_FILE), os.O_CREAT | os.O_EXCL | os.O_WRONLY)
            try:
                os.write(fd, pid_str)
            finally:
                os.close(fd)
            atexit.register(_release_lock)
            return
        except FileExistsError:
            # Lock есть — проверим живой ли владелец
            try:
                old_pid = int(LOCK_FILE.read_text(encoding="utf-8").strip())
            except Exception:
                old_pid = None
            if old_pid and _pid_alive(old_pid):
                print(
                    f"❌ Бот уже запущен (PID={old_pid}). "
                    f"Чтобы остановить: taskkill /PID {old_pid} /F",
                    file=sys.stderr,
                )
                sys.exit(1)
            # Мёртвый lock — удалить и попробовать ещё раз
            try:
                LOCK_FILE.unlink()
            except FileNotFoundError:
                pass
    # Не получилось за 2 попытки — выходим тихо, Task Scheduler перезапустит
    print("❌ Не удалось получить lock после 2 попыток", file=sys.stderr)
    sys.exit(1)


def _release_lock() -> None:
    try:
        if LOCK_FILE.exists():
            pid_in_file = LOCK_FILE.read_text(encoding="utf-8").strip()
            if pid_in_file == str(os.getpid()):
                LOCK_FILE.unlink()
    except Exception:
        pass


def _pid_alive(pid: int) -> bool:
    """Проверка что процесс с таким PID существует (Windows-совместимо)."""
    if pid <= 0:
        return False
    try:
        if os.name == "nt":
            import subprocess
            r = subprocess.run(
                ["tasklist", "/FI", f"PID eq {pid}", "/NH"],
                capture_output=True, text=True, timeout=5,
            )
            return str(pid) in r.stdout
        # POSIX
        os.kill(pid, 0)
        return True
    except Exception:
        return False


async def on_application_error(update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Глобальный error handler — не даём NetworkError/TimedOut уронить polling-цикл.

    Без него каждое сетевое падение проваливается в логи как «No error handlers
    are registered», и в некоторых случаях оставляет update-поток в degraded
    состоянии (inbound сообщения перестают доходить).
    """
    log = logging.getLogger("bot.main")
    err = context.error
    if isinstance(err, (NetworkError, TimedOut)):
        log.warning(f"Сетевая ошибка обработана: {type(err).__name__}: {err}")
    else:
        log.exception(f"Необработанное исключение в handler: {err}")


def setup_logging() -> None:
    handlers = [logging.FileHandler(config.LOG_FILE, encoding="utf-8")]
    # StreamHandler добавляем только если stderr доступен (под pythonw.exe он None)
    if sys.stderr is not None:
        try:
            handlers.append(logging.StreamHandler())
        except Exception:
            pass
    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s | %(levelname)s | %(name)s | %(message)s",
        handlers=handlers,
    )
    # Понижаем шум от httpx/telegram
    logging.getLogger("httpx").setLevel(logging.WARNING)
    logging.getLogger("apscheduler").setLevel(logging.WARNING)


def wait_for_telegram_reachable(
    max_minutes: int = 1440, interval_sec: int = 30, log_every_n: int = 10
) -> bool:
    """Дождаться сетевой доступности Telegram API.

    Реалистичный сценарий: пользователь включает ноут утром, VPN запускает
    через 5-30 минут (после кофе и т.п.). Бот терпеливо ждёт.

    Возвращает True если дождались, False — если упёрлись в max_minutes.
    После таймаута Task Scheduler перезапустит бота и цикл начнётся заново.
    """
    import urllib.request
    import urllib.error
    import time as _time

    log = logging.getLogger("bot.main")
    test_url = "https://api.telegram.org"
    max_attempts = (max_minutes * 60) // interval_sec  # 60 мин / 30 сек = 120
    last_log_attempt = 0

    for attempt in range(1, max_attempts + 1):
        try:
            with urllib.request.urlopen(test_url, timeout=10) as _:
                if attempt > 1:
                    log.info(f"Telegram доступен (с {attempt}-й попытки)")
                return True
        except (urllib.error.URLError, OSError, TimeoutError) as e:
            # Логируем не каждую попытку — каждые log_every_n (по умолч. 4 = раз в 2 мин)
            if attempt == 1 or attempt - last_log_attempt >= log_every_n:
                elapsed_min = (attempt * interval_sec) // 60
                log.warning(
                    f"Telegram недоступен ({elapsed_min} мин с момента старта): {e}. "
                    f"Жду VPN/сеть… (попытка {attempt}/{max_attempts})"
                )
                last_log_attempt = attempt
            if attempt < max_attempts:
                _time.sleep(interval_sec)

    log.error(
        f"Telegram недоступен после {max_minutes} мин ожидания — выход. "
        f"Task Scheduler перезапустит бот и цикл повторится."
    )
    return False


def main() -> None:
    setup_logging()
    log = logging.getLogger("bot.main")

    config.assert_token()
    db.init_schema()
    acquire_single_instance_lock()

    log.info("=== Bot starting ===")

    # Запоминаем время старта для job_daily_restart_check (uptime-based рестарт)
    from datetime import datetime as _dt
    db.set_state("last_bot_start_iso", _dt.now().isoformat())

    # Дожидаемся сетевой доступности — нужно если стартуем сразу при логине
    # и VPN/сеть ещё не успели подняться
    if not wait_for_telegram_reachable():
        log.error("Не дождались сети — выход. Task Scheduler перезапустит.")
        sys.exit(2)
    chat_id = db.get_chat_id()
    if chat_id:
        log.info(f"chat_id привязан: {chat_id}")
    else:
        log.info("chat_id ещё не привязан — ждём /start от пользователя")

    # Инициализация Garmin клиента (один на сессию бота)
    log.info("Инициализация Garmin клиента...")
    gc = garmin_client.login()
    if gc:
        log.info("Garmin клиент готов ✅")
    else:
        log.warning("Garmin клиент НЕ инициализирован — анализ зон работать не будет")

    # HTTPXRequest с расширенным connection pool — против Pool timeout,
    # который у нас уже валил бота при долгих сетевых разрывах (17.05).
    # Дефолтные значения PTB слишком тесные для нестабильной VPN/сети.
    request = HTTPXRequest(
        connection_pool_size=8,        # default 1 — основной фикс
        connect_timeout=20.0,          # default 5
        read_timeout=30.0,             # default 5
        write_timeout=20.0,            # default 5
        pool_timeout=10.0,             # default 1
    )
    application = (
        Application.builder()
        .token(config.TELEGRAM_BOT_TOKEN)
        .request(request)
        .build()
    )
    application.bot_data["garmin_client"] = gc
    application.add_error_handler(on_application_error)

    # Команды
    application.add_handler(CommandHandler("start", handlers.cmd_start))
    application.add_handler(CommandHandler("help", handlers.cmd_help))
    application.add_handler(CommandHandler("today", handlers.cmd_today))
    application.add_handler(CommandHandler("last", handlers.cmd_last))
    application.add_handler(CommandHandler("week", handlers.cmd_week))
    application.add_handler(CommandHandler("check", handlers.cmd_check))
    application.add_handler(CommandHandler("status", handlers.cmd_status))
    application.add_handler(CommandHandler("brief", handlers.cmd_brief))
    application.add_handler(CommandHandler("vo2", handlers.cmd_vo2))
    application.add_handler(CommandHandler("supps", handlers.cmd_supps))
    application.add_handler(CommandHandler("bads", handlers.cmd_supps))  # alias на русском
    application.add_handler(CommandHandler("feel", handlers.cmd_feel))
    application.add_handler(CommandHandler("digest", handlers.cmd_digest))

    # Subjective feedback: тапы по кнопкам 🔥/👍/😴
    application.add_handler(
        CallbackQueryHandler(handlers.on_feedback_callback, pattern=r"^feel\|")
    )
    # Текстовые ответы на вопрос «как зашло» — ловим только не-команды.
    # Регистрируем последним, чтобы команды успели сработать раньше.
    application.add_handler(
        MessageHandler(filters.TEXT & ~filters.COMMAND, handlers.on_text_feedback)
    )

    # Расписание
    scheduler.setup_scheduler(application)

    log.info("Бот в режиме polling Telegram. Ctrl+C для остановки.")

    # Защита от Bootstrap timeout (когда urllib видит api.telegram.org,
    # но httpx ещё не успел установить HTTP/2 коннект — PTB по умолчанию
    # делает 0 retries при инициализации и падает). Оборачиваем run_polling
    # в retry-цикл: при NetworkError/TimedOut при старте — sleep + повтор.
    import asyncio as _asyncio
    import time as _time
    max_bootstrap_attempts = 5
    for attempt in range(1, max_bootstrap_attempts + 1):
        try:
            application.run_polling(allowed_updates=["message", "callback_query"])
            break  # нормальное завершение run_polling
        except (NetworkError, TimedOut, _asyncio.TimeoutError) as e:
            log.warning(
                f"run_polling упал на сетевой ошибке "
                f"(attempt {attempt}/{max_bootstrap_attempts}): {type(e).__name__}: {e}"
            )
            if attempt == max_bootstrap_attempts:
                log.error("Все попытки исчерпаны — sys.exit(2), Task Scheduler перезапустит")
                sys.exit(2)
            _time.sleep(60)


if __name__ == "__main__":
    main()
