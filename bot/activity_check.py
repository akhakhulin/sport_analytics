"""Проверка новых активностей: детект → анализ → отчёт."""
from __future__ import annotations

import json
import logging
import re
from datetime import date
from typing import Optional

from telegram import InlineKeyboardButton, InlineKeyboardMarkup

from . import analyzer, config, db, plan_reader

log = logging.getLogger("bot.activity")


# Триггер на subjective-вопрос:
#   - длительная сессия (≥60 мин) — всегда чек-ин «как зашло»
#   - короче (45-60 мин) — только если есть отклонение от плана ≥10% или мисс по зоне
#   - <45 мин — никогда (короткие пробежки/прогулки не дёргаем)
FEEDBACK_DURATION_DEV_THRESHOLD = 0.10
MIN_DURATION_FOR_FEEDBACK_SEC = 45 * 60
ALWAYS_CHECKIN_DURATION_SEC = 60 * 60


def _parse_planned_duration_sec(plan_text: Optional[str]) -> Optional[int]:
    """Грубо вытаскивает плановую длительность из строки вида
    '2ч 30м', '1:00', '90м'. Возвращает секунды или None."""
    if not plan_text:
        return None
    txt = plan_text.lower()

    # "2ч 30м" / "1ч"
    m = re.search(r"(\d+)\s*ч(?:\s*(\d+)\s*м)?", txt)
    if m:
        h = int(m.group(1))
        mm = int(m.group(2)) if m.group(2) else 0
        return (h * 60 + mm) * 60

    # "1:30" / "0:45"
    m = re.search(r"(\d+):(\d{2})", txt)
    if m:
        return (int(m.group(1)) * 60 + int(m.group(2))) * 60

    # "90м" / "45 мин"
    m = re.search(r"(\d+)\s*м(?:ин)?\b", txt)
    if m:
        return int(m.group(1)) * 60

    return None


def _detect_deviation(activity: dict, plan: Optional[plan_reader.PlannedSession],
                      assessment: dict) -> tuple[Optional[str], Optional[float]]:
    """Возвращает (kind, pct) — повод задать subjective-вопрос, или (None, None)."""
    actual_sec = activity.get("duration_sec") or 0
    if actual_sec < MIN_DURATION_FOR_FEEDBACK_SEC:
        return None, None

    plan_text = plan.text if plan else None
    planned_sec = _parse_planned_duration_sec(plan_text)
    if planned_sec and planned_sec > 0:
        dev = (actual_sec - planned_sec) / planned_sec
        if abs(dev) >= FEEDBACK_DURATION_DEV_THRESHOLD:
            kind = "duration_over" if dev > 0 else "duration_under"
            return kind, round(abs(dev) * 100, 1)

    if assessment.get("matches_plan") == 0:
        return "zone_miss", None

    # Длительные сессии всегда — без отклонения, просто узнать как зашло
    if actual_sec >= ALWAYS_CHECKIN_DURATION_SEC:
        return "check_in", None

    return None, None


def _feedback_keyboard(activity_id: int) -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup([[
        InlineKeyboardButton("🔥 Огонь", callback_data=f"feel|{activity_id}|fire"),
        InlineKeyboardButton("👍 Норм", callback_data=f"feel|{activity_id}|normal"),
        InlineKeyboardButton("😴 Тяжко", callback_data=f"feel|{activity_id}|tired"),
    ]])


def _feedback_question_text(kind: str, dev_pct: Optional[float]) -> str:
    if kind == "duration_over" and dev_pct is not None:
        head = f"⚠️ Сделал на {dev_pct:.0f}% больше плана."
    elif kind == "duration_under" and dev_pct is not None:
        head = f"⚠️ Сделал на {dev_pct:.0f}% меньше плана."
    elif kind == "zone_miss":
        head = "⚠️ В плановой зоне был меньше нормы."
    elif kind == "check_in":
        head = "🔍 Длительная сессия — нужен фидбек."
    else:
        head = ""
    tail = (
        "Как зашло?\n\n"
        "Можешь тапнуть кнопку (быстрый ответ) или написать подробно "
        "ответом на это сообщение — почему так, что чувствовал, ветер/группа/самочувствие."
    )
    return f"{head}\n\n{tail}".strip()


def find_new_activities(since_date_iso: str) -> list[dict]:
    """Из БД активности за дату ≥since и без оценки."""
    with db.get_conn() as conn:
        rows = conn.execute(
            """SELECT a.activity_id, a.start_time_local, a.activity_type,
                      a.duration_sec, a.distance_m, a.avg_hr, a.max_hr,
                      a.training_effect_aer, a.training_effect_ana, a.elevation_gain_m
               FROM activities a
               LEFT JOIN training_assessment t ON t.activity_id = a.activity_id
               WHERE a.athlete_id=?
                 AND substr(a.start_time_local,1,10) >= ?
                 AND t.activity_id IS NULL
                 AND a.duration_sec >= 600  -- меньше 10 мин - перемещения, скип
               ORDER BY a.start_time_local""",
            (config.ATHLETE_ID, since_date_iso),
        ).fetchall()
    return [dict(r) for r in rows]


def match_plan_session(activity: dict) -> Optional[plan_reader.PlannedSession]:
    """Найти плановую сессию для активности по дате+спорту."""
    act_date = activity["start_time_local"][:10]
    sessions = plan_reader.for_date(date.fromisoformat(act_date))
    if not sessions:
        return None
    sport = activity["activity_type"]
    matching = [s for s in sessions if s.sport_for_match() == sport]
    if not matching:
        # fallback — любая сессия дня (отдаст утро первой)
        return sessions[0] if sessions else None
    # Если несколько (утро+вечер), берём по времени дня
    hour = int(activity["start_time_local"][11:13])
    if hour < 14:
        morning = [s for s in matching if s.part == "утро"]
        if morning:
            return morning[0]
    else:
        evening = [s for s in matching if s.part == "вечер"]
        if evening:
            return evening[0]
    return matching[0]


def format_activity_report(activity: dict, plan: Optional[plan_reader.PlannedSession],
                           assessment: dict) -> str:
    """Лаконичный отчёт: только соответствие плану."""
    raw_date = activity["start_time_local"][:10]   # "2026-05-04"
    act_date_dmy = f"{raw_date[8:10]}.{raw_date[5:7]}.{raw_date[0:4]}"  # "04.05.2026"
    act_time = activity["start_time_local"][11:16]
    sport_ru = {
        "running": "бег",
        "cycling": "вело",
        "strength_training": "силовая",
    }.get(activity["activity_type"], activity["activity_type"])

    dur_min = activity["duration_sec"] / 60 if activity["duration_sec"] else 0
    dist_km = activity["distance_m"] / 1000 if activity["distance_m"] else 0

    lines: list[str] = []
    lines.append(f"✅ Активность сохранена ({act_date_dmy} {act_time})")
    lines.append(f"  {sport_ru}: {dur_min:.0f}м / {dist_km:.2f}км / "
                 f"HR {int(activity['avg_hr'] or 0)} avg")
    lines.append("")

    if plan:
        lines.append(f"📋 План: {plan.text}")
    else:
        lines.append("📋 План: не найден")
    lines.append("")

    if assessment.get("matches_plan") == 1:
        lines.append(f"🎯 Соответствие плану: ✅")
        lines.append(assessment["comment"])
    elif assessment.get("matches_plan") == 0:
        lines.append(f"🎯 Соответствие плану: ⚠️")
        lines.append(assessment["comment"])
    else:
        lines.append(f"🎯 Соответствие плану: —")
        lines.append(assessment.get("comment") or "проверка не выполнена")

    if assessment.get("all_zones"):
        lines.append("")
        lines.append(f"Зоны: {assessment['all_zones']}")

    return "\n".join(lines)


async def check_and_report(bot, chat_id: int, since_date_iso: str,
                           garmin_client) -> int:
    """Найти новые активности, оценить, отправить отчёты. Вернуть число обработанных."""
    activities = find_new_activities(since_date_iso)
    if not activities:
        log.info("Новых активностей нет")
        return 0

    sent = 0
    for act in activities:
        if db.is_activity_assessed(act["activity_id"]):
            continue

        # Атомарный claim: гарантирует, что отчёт по активности отправит
        # ровно один инстанс — даже если параллельно работают двое или
        # бот перезапустился между send_message и save_assessment.
        if not db.claim_activity_for_report(act["activity_id"]):
            log.info(
                f"activity {act['activity_id']} уже зареcервирована — skip"
            )
            continue

        plan = match_plan_session(act)
        if garmin_client:
            assessment = analyzer.assess_activity(
                act["activity_id"],
                act["activity_type"],
                plan,
                garmin_client,
                config.ZONE_COMPLIANCE_THRESHOLD,
            )
        else:
            assessment = {
                "plan_text": plan.text if plan else None,
                "plan_zone": plan.target_zone() if plan else None,
                "actual_pct": None,
                "matches_plan": None,
                "comment": "Garmin client недоступен",
            }

        text = format_activity_report(act, plan, assessment)
        try:
            await bot.send_message(chat_id=chat_id, text=text)
            sent += 1
        except Exception as e:
            log.exception(f"send report failed: {e}")
            continue

        db.save_assessment(
            activity_id=act["activity_id"],
            plan_text=assessment.get("plan_text"),
            plan_zone=assessment.get("plan_zone"),
            actual_pct=assessment.get("actual_pct"),
            matches=assessment.get("matches_plan"),
            raw_json=json.dumps(assessment, ensure_ascii=False),
        )
        db.log_message(
            "activity",
            text,
            chat_id=str(chat_id),
            related_activity_id=act["activity_id"],
            related_date=act["start_time_local"][:10],
        )

        # Subjective-вопрос — длительные всегда, остальное по триггерам;
        # уже спрошенное не дублируем.
        if not db.is_feedback_asked(act["activity_id"]):
            kind, dev_pct = _detect_deviation(act, plan, assessment)
            if kind:
                q_text = _feedback_question_text(kind, dev_pct)
                try:
                    sent_msg = await bot.send_message(
                        chat_id=chat_id,
                        text=q_text,
                        reply_markup=_feedback_keyboard(act["activity_id"]),
                    )
                    db.mark_feedback_asked(act["activity_id"], kind, dev_pct)
                    # Запоминаем «ждём текстового ответа» в течение 6 ч.
                    # Если пользователь напишет в этом окне — текст пойдёт в notes.
                    db.set_pending_text_feedback(
                        activity_id=act["activity_id"],
                        prompt_message_id=sent_msg.message_id,
                        ttl_hours=6,
                    )
                except Exception as e:
                    log.exception(f"send feedback question failed: {e}")
    return sent
