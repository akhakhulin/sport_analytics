"""Воскресный недельный дайджест.

Что внутри:
- Объём план/факт по сессиям недели (Пн-Вс)
- Распределение времени по HR-зонам
- RHR / HRV тренд против предыдущей недели
- Сводка subjective feedback (🔥/👍/😴 + ключевые заметки)
- Decoupling длительной (если была)
- 1-3 коротких флага «что заметил»

Никаких правок плана — это сводка, не редактор.
"""
from __future__ import annotations

import logging
from datetime import date, datetime, timedelta
from typing import Optional

from . import config, db, plan_reader

log = logging.getLogger("bot.weekly")


_FEEL_LABEL = {"fire": "🔥", "normal": "👍", "tired": "😴", "manual_text": "📝"}


def _week_bounds(any_day: date) -> tuple[date, date]:
    """Понедельник-воскресенье недели, в которой лежит any_day."""
    start = any_day - timedelta(days=any_day.weekday())
    return start, start + timedelta(days=6)


def _fetch_week_activities(start: date, end: date) -> list[dict]:
    with db.get_conn() as conn:
        rows = conn.execute(
            """SELECT activity_id, start_time_local, activity_type, activity_name,
                      duration_sec, distance_m, avg_hr, max_hr, training_effect_aer,
                      training_effect_ana, raw_json
                 FROM activities
                WHERE athlete_id=?
                  AND substr(start_time_local,1,10) BETWEEN ? AND ?
                  AND duration_sec >= 600
                ORDER BY start_time_local""",
            (config.ATHLETE_ID, start.isoformat(), end.isoformat()),
        ).fetchall()
    return [dict(r) for r in rows]


def _fetch_daily_stats(start: date, end: date) -> list[dict]:
    with db.get_conn() as conn:
        rows = conn.execute(
            """SELECT day, resting_hr, avg_stress, body_battery_high, body_battery_low
                 FROM daily_stats
                WHERE athlete_id=? AND day BETWEEN ? AND ?
                ORDER BY day""",
            (config.ATHLETE_ID, start.isoformat(), end.isoformat()),
        ).fetchall()
    return [dict(r) for r in rows]


def _fetch_hrv(start: date, end: date) -> list[dict]:
    with db.get_conn() as conn:
        rows = conn.execute(
            """SELECT day, last_night_avg, weekly_avg, status
                 FROM hrv WHERE athlete_id=? AND day BETWEEN ? AND ?
                ORDER BY day""",
            (config.ATHLETE_ID, start.isoformat(), end.isoformat()),
        ).fetchall()
    return [dict(r) for r in rows]


def _fetch_feedback_for_activities(activity_ids: list[int]) -> dict[int, dict]:
    if not activity_ids:
        return {}
    qs = ",".join("?" * len(activity_ids))
    with db.get_conn() as conn:
        rows = conn.execute(
            f"""SELECT activity_id, feeling, notes
                  FROM subjective_feedback
                 WHERE activity_id IN ({qs})""",
            activity_ids,
        ).fetchall()
    return {int(r["activity_id"]): dict(r) for r in rows}


def _avg(xs: list[Optional[float]]) -> Optional[float]:
    vals = [x for x in xs if x is not None]
    if not vals:
        return None
    return sum(vals) / len(vals)


def _zone_breakdown(acts: list[dict]) -> dict[str, float]:
    """Суммарное время в зонах (минуты) по неделе."""
    import json as _json
    total = {f"Z{i}": 0.0 for i in range(1, 6)}
    for a in acts:
        try:
            d = _json.loads(a["raw_json"]) if a.get("raw_json") else {}
        except Exception:
            d = {}
        for i in range(1, 6):
            sec = d.get(f"hrTimeInZone_{i}") or 0
            total[f"Z{i}"] += sec / 60.0
    return total


def compose_weekly_digest(any_day_in_week: Optional[date] = None) -> str:
    today = any_day_in_week or date.today()
    week_start, week_end = _week_bounds(today)
    prev_start, prev_end = week_start - timedelta(days=7), week_start - timedelta(days=1)

    acts = _fetch_week_activities(week_start, week_end)
    daily = _fetch_daily_stats(week_start, week_end)
    daily_prev = _fetch_daily_stats(prev_start, prev_end)
    hrv = _fetch_hrv(week_start, week_end)
    hrv_prev = _fetch_hrv(prev_start, prev_end)
    feedback = _fetch_feedback_for_activities([a["activity_id"] for a in acts])

    lines: list[str] = []
    lines.append(
        f"📊 *Дайджест недели {week_start.strftime('%d.%m')}–{week_end.strftime('%d.%m')}*"
    )
    lines.append("")

    # === Объём ===
    total_min = sum((a["duration_sec"] or 0) for a in acts) / 60
    total_km = sum((a["distance_m"] or 0) for a in acts) / 1000
    by_sport: dict[str, dict] = {}
    for a in acts:
        sp = a["activity_type"] or "other"
        b = by_sport.setdefault(sp, {"min": 0.0, "km": 0.0, "n": 0})
        b["min"] += (a["duration_sec"] or 0) / 60
        b["km"] += (a["distance_m"] or 0) / 1000
        b["n"] += 1

    sport_ru = {
        "running": "бег", "cycling": "вело", "indoor_cycling": "вело-зал",
        "strength_training": "силовая", "hiking": "ходьба",
        "cross_country_skiing": "лыжи",
    }

    lines.append("🏋 *Объём*")
    lines.append(f"Всего: {total_min/60:.1f} ч / {total_km:.1f} км / {len(acts)} сессий")
    for sp, b in sorted(by_sport.items(), key=lambda kv: -kv[1]["min"]):
        name = sport_ru.get(sp, sp)
        km_str = f" / {b['km']:.1f} км" if b['km'] >= 0.5 else ""
        lines.append(f"  • {name}: {b['min']/60:.1f} ч{km_str} ({b['n']})")
    lines.append("")

    # === HR-зоны ===
    z = _zone_breakdown(acts)
    z_total = sum(z.values())
    if z_total > 0:
        lines.append("📈 *Зоны (% времени)*")
        line = "  "
        for k in ("Z1", "Z2", "Z3", "Z4", "Z5"):
            pct = (z[k] / z_total) * 100
            line += f"{k}={pct:.0f}%  "
        lines.append(line.rstrip())
        # Полярность: Z1+Z2 vs Z4+Z5
        easy = (z["Z1"] + z["Z2"]) / z_total * 100
        hard = (z["Z4"] + z["Z5"]) / z_total * 100
        lines.append(f"  Polar: easy {easy:.0f}% | hard {hard:.0f}%")
        lines.append("")

    # === RHR / HRV тренд ===
    rhr_now = _avg([d.get("resting_hr") for d in daily])
    rhr_prev = _avg([d.get("resting_hr") for d in daily_prev])
    hrv_now = _avg([h.get("last_night_avg") for h in hrv])
    hrv_prev_v = _avg([h.get("last_night_avg") for h in hrv_prev])

    lines.append("💓 *Восстановление*")
    if rhr_now is not None:
        delta = (
            f" ({rhr_now - rhr_prev:+.1f} к прошлой)"
            if rhr_prev is not None else ""
        )
        lines.append(f"  RHR avg: {rhr_now:.0f}{delta}")
    if hrv_now is not None:
        delta = (
            f" ({hrv_now - hrv_prev_v:+.1f} к прошлой)"
            if hrv_prev_v is not None else ""
        )
        lines.append(f"  HRV avg: {hrv_now:.0f}{delta}")
    statuses = [h.get("status") for h in hrv if h.get("status")]
    if statuses:
        from collections import Counter
        c = Counter(statuses)
        lines.append("  HRV дни: " + ", ".join(f"{k}×{v}" for k, v in c.most_common()))
    lines.append("")

    # === Subjective feedback ===
    fb_count: dict[str, int] = {}
    notes_blocks: list[str] = []
    for a in acts:
        fb = feedback.get(a["activity_id"])
        if not fb or not fb.get("feeling"):
            continue
        feel = fb["feeling"]
        fb_count[feel] = fb_count.get(feel, 0) + 1
        if fb.get("notes"):
            d = a["start_time_local"][8:10] + "." + a["start_time_local"][5:7]
            sp = sport_ru.get(a["activity_type"], a["activity_type"])
            notes_blocks.append(f"  {d} {sp}: {fb['notes'][:200]}")

    if fb_count or notes_blocks:
        lines.append("🗣 *Фидбек*")
        if fb_count:
            sym = " ".join(
                f"{_FEEL_LABEL.get(k, k)}×{v}" for k, v in fb_count.items()
            )
            lines.append(f"  Сводка: {sym}")
        if notes_blocks:
            lines.append("  Заметки:")
            for nb in notes_blocks[:8]:
                lines.append(nb)
        lines.append("")

    # === Простые флаги «что заметил» ===
    flags: list[str] = []
    if rhr_now and rhr_prev and rhr_now - rhr_prev >= 3:
        flags.append("⚠️ RHR вырос на 3+ удара — возможна накопленная усталость")
    if hrv_now and hrv_prev_v and hrv_now - hrv_prev_v <= -5:
        flags.append("⚠️ HRV упал на 5+ — нагрузка переваривается тяжелее")
    if z_total > 0:
        easy_pct = (z["Z1"] + z["Z2"]) / z_total * 100
        hard_pct = (z["Z4"] + z["Z5"]) / z_total * 100
        if easy_pct < 70:
            flags.append(f"⚠️ Easy всего {easy_pct:.0f}% (норма 80%) — слишком много Z3-Z5")
        if hard_pct > 25:
            flags.append(f"⚠️ Hard {hard_pct:.0f}% (норма ≤20%) — пересушенно интенсивностью")
    if fb_count.get("tired", 0) >= 2:
        flags.append(f"⚠️ Несколько 😴 за неделю ({fb_count['tired']}) — стоит обсудить")

    if flags:
        lines.append("🚩 *Флаги*")
        for f in flags:
            lines.append(f"  {f}")
    else:
        lines.append("✅ Флагов нет — неделя в норме")

    return "\n".join(lines)


async def send_weekly_digest(bot, chat_id: int,
                             any_day_in_week: Optional[date] = None) -> str:
    text = compose_weekly_digest(any_day_in_week)
    await bot.send_message(chat_id=chat_id, text=text, parse_mode="Markdown")
    db.log_message("weekly_digest", text, chat_id=str(chat_id))
    return text
