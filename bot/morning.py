"""Утренний регламент: синк + отчёт."""
from __future__ import annotations

import logging
import subprocess
import sys
from datetime import date, timedelta
from typing import Optional

from . import briefs, config, db, plan_reader

log = logging.getLogger("bot.morning")


def run_garmin_sync() -> bool:
    """Дёргает существующий garmin_sync.py из корня проекта."""
    script = config.PROJECT_ROOT / "garmin_sync.py"
    if not script.exists():
        log.error(f"garmin_sync.py не найден: {script}")
        return False
    try:
        result = subprocess.run(
            [sys.executable, str(script)],
            cwd=str(config.PROJECT_ROOT),
            capture_output=True,
            text=True,
            timeout=180,
        )
        if result.returncode == 0:
            log.info("Garmin sync: OK")
            return True
        log.error(f"Garmin sync exit {result.returncode}: {result.stderr[-500:]}")
        return False
    except Exception as e:
        log.exception(f"sync failed: {e}")
        return False


def fetch_recovery_data(target_date: date) -> dict:
    """Берёт RHR / HRV / Sleep / BB / Stress на дату из БД."""
    res: dict = {
        "date": target_date.isoformat(),
        "rhr": None,
        "rhr_baseline": None,
        "hrv_night": None,
        "hrv_weekly": None,
        "hrv_status": None,
        "bb_max": None,
        "bb_min": None,
        "stress_avg": None,
    }
    target = target_date.isoformat()
    week_ago = (target_date - timedelta(days=7)).isoformat()

    with db.get_conn() as conn:
        # Текущий день
        row = conn.execute(
            """SELECT resting_hr, avg_stress, body_battery_high, body_battery_low
               FROM daily_stats
               WHERE athlete_id=? AND day=?""",
            (config.ATHLETE_ID, target),
        ).fetchone()
        if row:
            res["rhr"] = row["resting_hr"]
            res["stress_avg"] = row["avg_stress"]
            res["bb_max"] = row["body_battery_high"]
            res["bb_min"] = row["body_battery_low"]

        # Базовый RHR — минимальный за последние 7 дней
        row = conn.execute(
            """SELECT MIN(resting_hr) AS rhr_min
               FROM daily_stats
               WHERE athlete_id=? AND day BETWEEN ? AND ?
                     AND resting_hr IS NOT NULL""",
            (config.ATHLETE_ID, week_ago, target),
        ).fetchone()
        if row:
            res["rhr_baseline"] = row["rhr_min"]

        # HRV
        row = conn.execute(
            """SELECT last_night_avg, weekly_avg, status
               FROM hrv WHERE athlete_id=? AND day=?""",
            (config.ATHLETE_ID, target),
        ).fetchone()
        if row:
            res["hrv_night"] = row["last_night_avg"]
            res["hrv_weekly"] = row["weekly_avg"]
            res["hrv_status"] = row["status"]
    return res


def format_recovery_line(rec: dict) -> str:
    parts = []
    rhr = rec.get("rhr")
    base = rec.get("rhr_baseline")
    if rhr is not None:
        if base and rhr - base != 0:
            sign = "+" if rhr > base else ""
            parts.append(f"RHR {rhr} ({sign}{rhr - base} от базы {base})")
        else:
            parts.append(f"RHR {rhr}")
    hrv_n = rec.get("hrv_night")
    if hrv_n is not None:
        parts.append(f"HRV {int(hrv_n)}")
    bb_max = rec.get("bb_max")
    if bb_max is not None:
        parts.append(f"BB {bb_max}")
    return " | ".join(parts) if parts else "(нет данных за сегодня)"


def format_status_line(rec: dict) -> str:
    status = rec.get("hrv_status")
    icon = {
        "BALANCED": "✅",
        "UNBALANCED": "⚠️",
        "LOW": "⚠️",
        "POOR": "🔴",
    }.get(status, "ℹ️")
    return f"{icon} {status}" if status else ""


def assess_state_for_recommendation(rec: dict) -> str:
    """Краткая рекомендация по результатам recovery."""
    rhr = rec.get("rhr")
    base = rec.get("rhr_baseline") or rhr
    hrv = rec.get("hrv_night")

    if rhr is None or hrv is None or base is None:
        return "💡 Данные не полные — план как обычно, наблюдай по ощущениям"

    if rhr >= base + 5 or hrv < 50:
        return "🔴 Восстановление слабое — лучше отдых или объём -50%"
    if rhr >= base + 3 or hrv < 60:
        return "⚠️ Восстановление частичное — снизь объём на 30%"
    return "💡 Состояние норм — план без сокращений"


def compose_morning_message(target_date: date) -> str:
    rec = fetch_recovery_data(target_date)
    sessions = plan_reader.for_date(target_date)

    lines: list[str] = []
    lines.append(f"🌅 Доброе утро!")
    lines.append("")
    lines.append("📊 " + format_recovery_line(rec))
    status = format_status_line(rec)
    if status:
        lines.append(status)
    lines.append("")

    # Утренняя гидратация — для густой крови (КардиоМагнил протокол)
    lines.append("💧 Сразу после подъёма: 400-500 мл воды (за ночь кровь сгустилась)")
    lines.append("")

    weekday_ru = ["Пн", "Вт", "Ср", "Чт", "Пт", "Сб", "Вс"][target_date.weekday()]
    lines.append(f"📋 Сегодня ({weekday_ru} {target_date.strftime('%d.%m')}):")
    if not sessions:
        lines.append("— план не найден на эту дату")
    else:
        for s in sessions:
            icon = "☀" if s.part == "утро" else "🌙"
            lines.append(f"{icon} {s.text}")
    lines.append("")

    lines.append(assess_state_for_recommendation(rec))
    return "\n".join(lines)


async def send_morning(bot, chat_id: int, target_date: Optional[date] = None) -> str:
    """Сформировать утреннее сообщение и отправить.

    Помимо основного сообщения, отправляет отдельно бриф(ы) на силовую/кор/плиометрику
    если они есть в плане сегодня. Возвращает текст основного сообщения.
    """
    target = target_date or date.today()
    text = compose_morning_message(target)
    await bot.send_message(chat_id=chat_id, text=text)
    db.log_message("morning", text, chat_id=str(chat_id), related_date=target.isoformat())

    # Брифы по силовой/кор/плиометрике
    sessions = plan_reader.for_date(target)
    for brief_text in briefs.for_today(sessions):
        try:
            await bot.send_message(chat_id=chat_id, text=brief_text)
            db.log_message(
                "brief", brief_text, chat_id=str(chat_id),
                related_date=target.isoformat(),
            )
        except Exception:
            pass  # не валим утренний регламент из-за брифа

    db.mark_morning_sent(target.isoformat())
    return text
