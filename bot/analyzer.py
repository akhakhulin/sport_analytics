"""Анализатор активности: сверка зон с планом."""
from __future__ import annotations

import json
import logging
from typing import Optional

from . import db
from .plan_reader import PlannedSession, zone_to_set

log = logging.getLogger("bot.analyzer")


def get_zone_floors(athlete_id: str, sport: str) -> Optional[list[int]]:
    """Возвращает [Z1_floor, Z2_floor, ..., Z5_floor] для спорта и атлета.

    Для running берём 'RUNNING', для cycling — 'CYCLING', иначе 'DEFAULT'.
    """
    sport_key = {
        "running": "RUNNING",
        "cycling": "CYCLING",
    }.get(sport, "DEFAULT")
    with db.get_conn() as conn:
        row = conn.execute(
            """SELECT zone1_floor, zone2_floor, zone3_floor, zone4_floor, zone5_floor
               FROM hr_zones WHERE athlete_id=? AND sport=?""",
            (athlete_id, sport_key),
        ).fetchone()
    if not row:
        return None
    return [row["zone1_floor"], row["zone2_floor"], row["zone3_floor"],
            row["zone4_floor"], row["zone5_floor"]]


def fetch_zone_breakdown_via_api(activity_id: int, garmin_client) -> Optional[list[dict]]:
    """Получить time-in-zones через garminconnect API.

    Возвращает список из 5 dict с ключами:
      zoneNumber, secsInZone, zoneLowBoundary
    Или None, если не удалось.
    """
    try:
        zones = garmin_client.get_activity_hr_in_timezones(activity_id)
        if zones:
            return zones
    except Exception as e:
        log.warning(f"get_activity_hr_in_timezones({activity_id}) failed: {e}")
    return None


def compute_zone_pct_in_target(
    zone_breakdown: list[dict], target_zones: set[int]
) -> Optional[float]:
    """Из API-разбивки на зоны вычислить % времени в целевых зонах."""
    if not zone_breakdown:
        return None
    total = sum(z.get("secsInZone", 0) or 0 for z in zone_breakdown)
    if total <= 0:
        return None
    in_target = sum(
        (z.get("secsInZone", 0) or 0)
        for z in zone_breakdown
        if z.get("zoneNumber") in target_zones
    )
    return round(in_target / total, 4)


def assess_activity(
    activity_id: int,
    sport: str,
    plan_session: Optional[PlannedSession],
    garmin_client,
    threshold: float,
) -> dict:
    """Полная оценка тренировки.

    Возвращает dict с полями:
      plan_text, plan_zone, actual_pct, matches_plan, comment
    """
    result = {
        "plan_text": plan_session.text if plan_session else None,
        "plan_zone": None,
        "actual_pct": None,
        "matches_plan": None,
        "comment": "",
    }

    if not plan_session:
        result["comment"] = "плановой сессии не найдено"
        return result

    plan_zone = plan_session.target_zone()
    result["plan_zone"] = plan_zone

    if not plan_zone:
        result["comment"] = "в плановой сессии нет HR-зоны → сверка не делается"
        return result

    # Получаем разбивку зон
    breakdown = fetch_zone_breakdown_via_api(activity_id, garmin_client)
    if not breakdown:
        result["comment"] = "не удалось получить time-in-zones из Garmin"
        return result

    target = zone_to_set(plan_zone)
    pct = compute_zone_pct_in_target(breakdown, target)
    result["actual_pct"] = pct

    if pct is None:
        result["comment"] = "пустые зоны в Garmin"
        return result

    matches = 1 if pct >= threshold else 0
    result["matches_plan"] = matches
    if matches:
        result["comment"] = f"✅ {pct*100:.0f}% времени в {plan_zone} (план ≥{threshold*100:.0f}%)"
    else:
        result["comment"] = (
            f"⚠️ только {pct*100:.0f}% времени в {plan_zone} (план ≥{threshold*100:.0f}%)"
        )

    # Доп.инфо: разбивка по всем 5 зонам
    total = sum(z.get("secsInZone", 0) or 0 for z in breakdown)
    if total > 0:
        pcts = []
        for z in breakdown:
            zn = z.get("zoneNumber")
            sec = z.get("secsInZone", 0) or 0
            pcts.append(f"Z{zn} {sec/total*100:.0f}%")
        result["all_zones"] = " / ".join(pcts)

    return result
