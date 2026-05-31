"""APScheduler tasks: утренний регламент + 30-мин polling + воскресный дайджест + watchdog."""
from __future__ import annotations

import logging
import sys
from datetime import date, datetime, time, timedelta

from . import activity_check, config, db, morning, weekly_digest

log = logging.getLogger("bot.scheduler")

# Watchdog state — счётчик подряд неудачных connectivity-проверок.
# После N подряд провалов делаем sys.exit(2) → Task Scheduler перезапустит бота.
_connectivity_failures = 0
_WATCHDOG_FAIL_THRESHOLD = 3


async def job_heartbeat(application) -> None:
    """Каждую минуту обновляем heartbeat для /status."""
    db.heartbeat()


async def job_morning_routine(application) -> None:
    """Утренний регламент: sync Garmin → если ещё не отправлял сегодня → отчёт."""
    today = date.today()
    today_iso = today.isoformat()
    now = datetime.now()

    if db.is_morning_sent_today(today_iso):
        log.info(f"Утренний отчёт за {today_iso} уже отправлен — пропуск")
        return

    if not (config.MORNING_HOUR_RANGE[0] <= now.hour < config.MORNING_HOUR_RANGE[1]):
        log.info(
            f"Сейчас {now.strftime('%H:%M')}, вне окна "
            f"{config.MORNING_HOUR_RANGE[0]:02d}-{config.MORNING_HOUR_RANGE[1]:02d}:00 — отложено"
        )
        return

    chat_id = db.get_chat_id()
    if not chat_id:
        log.warning("chat_id не задан — пропускаю утренний отчёт")
        return

    log.info(f"Утренний регламент: sync Garmin → отчёт")
    morning.run_garmin_sync()
    text = await morning.send_morning(application.bot, int(chat_id), today)
    log.info(f"Утренний отчёт отправлен ({len(text)} chars)")


async def job_connectivity_watchdog(application) -> None:
    """Каждые 5 мин — мягкий тест связи с Telegram (bot.get_me()).

    Только логирует, не убивает процесс. PTB сам retry'ит outbound при
    сетевых разрывах, а error_handler в main.py ловит exception'ы в
    handler'ах — этого достаточно для устойчивости. Раньше тут был
    sys.exit(2) после 3 провалов, но он создавал каскад: сеть тупит
    >5 мин → бот выходит → Task Scheduler перезапускает 5 раз → попадает
    в ту же сеть → опять exit → scheduler сдаётся → бот мёртв до ручного
    рестарта. Теперь watchdog только сигнализирует.
    """
    global _connectivity_failures
    try:
        await application.bot.get_me()
        if _connectivity_failures > 0:
            log.info(f"Connectivity восстановлен после {_connectivity_failures} провалов")
        _connectivity_failures = 0
    except Exception as e:
        _connectivity_failures += 1
        log.warning(
            f"Watchdog: connectivity check провален "
            f"(подряд {_connectivity_failures}): {e}"
        )


async def job_daily_restart_check(application) -> None:
    """Профилактический ежедневный рестарт — обнуляет long-poll стрим.

    Логика: если с последнего рестарта прошло **>18 часов** — выходим
    (sys.exit(0)), Task Scheduler поднимет бота за минуту.

    Раньше был привязан к окну 04:00-04:14, но если компьютер спал в это
    время — job выполнялся как catchup в 12:00, отбрасывался по условию
    `now.hour != 4` и рестарт не происходил вообще. Поэтому теперь —
    по uptime, чтобы покрыть случай «комп проспал ночь».

    Дополнительно ждём окно с 03:00 до 11:00 утра — чтоб не рестартовать
    посреди дневной активности пользователя.
    """
    now = datetime.now()
    # Дневное окно — не трогаем (пользователь работает с ботом)
    if now.hour < 3 or now.hour > 11:
        return

    last_restart_iso = db.get_state("last_bot_start_iso")
    if last_restart_iso:
        try:
            last_restart = datetime.fromisoformat(last_restart_iso)
            hours_up = (now - last_restart).total_seconds() / 3600
            if hours_up < 18:
                return
        except Exception:
            pass

    log.info(
        f"Профилактический рестарт — uptime превысил 18ч "
        f"(last_start={last_restart_iso}, now={now.isoformat()}). "
        f"Спавню новый инстанс и выхожу."
    )
    # Спавним новый процесс детачем — он поднимется ДО того, как мы умрём.
    # Lock-файл удерживается до sys.exit, новый инстанс подождёт ~3с и заберёт его.
    try:
        import subprocess
        bat = config.PROJECT_ROOT / "bot" / "start_bot.bat"
        DETACHED_PROCESS = 0x00000008
        CREATE_NEW_PROCESS_GROUP = 0x00000200
        subprocess.Popen(
            ["cmd", "/c", str(bat)],
            cwd=str(config.PROJECT_ROOT),
            creationflags=DETACHED_PROCESS | CREATE_NEW_PROCESS_GROUP,
            stdin=subprocess.DEVNULL,
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
            close_fds=True,
        )
        log.info("Новый инстанс запущен через start_bot.bat (detached).")
    except Exception as e:
        log.exception(f"Не удалось спавнить новый инстанс: {e}")
    # Небольшая задержка, чтобы новый инстанс успел стартовать (и упереться в lock),
    # а потом дождаться нашего sys.exit и сразу зайти при retry.
    import time as _t
    _t.sleep(2)
    sys.exit(0)


async def job_weekly_digest(application) -> None:
    """Воскресенье 20:00 — сводка недели в Telegram."""
    today = date.today()
    today_iso = today.isoformat()
    if db.get_state(f"weekly_digest_sent_{today_iso}") == "1":
        log.info(f"Дайджест за {today_iso} уже отправлен — пропуск")
        return
    chat_id = db.get_chat_id()
    if not chat_id:
        log.warning("chat_id не задан — пропуск дайджеста")
        return
    log.info("Отправка воскресного дайджеста")
    try:
        await weekly_digest.send_weekly_digest(application.bot, int(chat_id))
        db.set_state(f"weekly_digest_sent_{today_iso}", "1")
    except Exception as e:
        log.exception(f"weekly digest failed: {e}")


async def job_activity_poll(application) -> None:
    """Каждые N минут: проверить новые активности и отправить отчёты."""
    chat_id = db.get_chat_id()
    if not chat_id:
        log.debug("chat_id не задан — skip polling")
        return

    garmin_client = application.bot_data.get("garmin_client")
    if not garmin_client:
        log.debug("garmin_client не инициализирован — skip polling")
        return

    log.info("Polling: проверка новых активностей")
    morning.run_garmin_sync()

    since = (date.today() - timedelta(days=2)).isoformat()
    n = await activity_check.check_and_report(
        bot=application.bot,
        chat_id=int(chat_id),
        since_date_iso=since,
        garmin_client=garmin_client,
    )
    if n > 0:
        log.info(f"Отправлено отчётов: {n}")


def setup_scheduler(application) -> None:
    """Зарегистрировать задачи в JobQueue Telegram-приложения."""
    jq = application.job_queue
    if not jq:
        log.error("JobQueue недоступен (надо ставить python-telegram-bot[job-queue])")
        return

    # Утренний trigger: при старте + каждые 5 минут пытаться (если ПК спал утром)
    jq.run_once(lambda ctx: job_morning_routine(application), when=10, name="morning_at_startup")
    jq.run_repeating(
        lambda ctx: job_morning_routine(application),
        interval=300,  # 5 мин
        first=300,
        name="morning_retry",
    )

    # Polling активностей
    jq.run_repeating(
        lambda ctx: job_activity_poll(application),
        interval=config.ACTIVITY_POLL_INTERVAL_MIN * 60,
        first=180,  # 3 мин после старта
        name="activity_poll",
    )

    # Heartbeat каждые 60 сек — для /status
    jq.run_repeating(
        lambda ctx: job_heartbeat(application),
        interval=60,
        first=5,
        name="heartbeat",
    )

    # Воскресный дайджест: ежедневно проверяем — если воскресенье и время ≥20:00,
    # отправляем (с защитой от повторов через bot_state).
    jq.run_repeating(
        lambda ctx: _maybe_weekly_digest(application),
        interval=900,  # каждые 15 мин
        first=600,
        name="weekly_digest_check",
    )

    # Connectivity watchdog: каждые 5 мин проверяет связь с Telegram.
    # 3 подряд провала = sys.exit(2), Task Scheduler перезапустит.
    jq.run_repeating(
        lambda ctx: job_connectivity_watchdog(application),
        interval=300,  # каждые 5 мин
        first=300,
        name="connectivity_watchdog",
    )

    # Ежедневный профилактический рестарт в 04:00 — обнуляет long-poll стрим
    # чтобы inbound не застревал после ночной спячки ПК.
    jq.run_repeating(
        lambda ctx: job_daily_restart_check(application),
        interval=300,  # проверка каждые 5 мин
        first=600,
        name="daily_restart_check",
    )

    log.info(
        f"Задачи зарегистрированы: morning (в окне {config.MORNING_HOUR_RANGE}), "
        f"activity poll каждые {config.ACTIVITY_POLL_INTERVAL_MIN} мин, heartbeat 60с, "
        f"weekly digest вс 20:00+, connectivity watchdog 5 мин"
    )


async def _maybe_weekly_digest(application) -> None:
    """Если воскресенье после 20:00 локального времени — отправить (1 раз)."""
    now = datetime.now()
    if now.weekday() != 6:  # 0=пн, 6=вс
        return
    if now.hour < 20:
        return
    await job_weekly_digest(application)
