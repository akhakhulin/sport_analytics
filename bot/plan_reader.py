"""Парсер плана из Excel «Тренировки списком»."""
from __future__ import annotations

import re
from dataclasses import dataclass
from datetime import date
from typing import Optional

import openpyxl

from . import config


@dataclass
class PlannedSession:
    date: str         # YYYY-MM-DD
    day_short: str    # Пн / Вт / ...
    week_num: int
    part: str         # утро / вечер
    text: str
    type: str         # бег / вело / ст-омв / контроль / ...
    hours: float

    def target_zone(self) -> Optional[str]:
        """Извлечь плановую HR-зону из текста (Z1, Z2, Z1-Z2 и т.п.)."""
        return extract_zone(self.text)

    def is_runnable(self) -> bool:
        """Эту сессию имеет смысл сверять с активностью Garmin."""
        return self.type not in ("отдых",)

    def sport_for_match(self) -> Optional[str]:
        """Какому Garmin activity_type соответствует тип сессии."""
        t = self.type
        if t in ("бег", "бег-длит", "контроль"):
            return "running"
        if t in ("вело", "вело-длит"):
            return "cycling"
        if t == "плиометрика":
            return "running"  # часто лог. в Garmin как running
        if t in ("ст-омв", "ст-омв-пик", "ст-тон", "кор"):
            return "strength_training"
        return None


_ZONE_RE = re.compile(r"\bZ([1-5])(?:\s*[-–]\s*Z?([1-5]))?\b")


def extract_zone(text: str) -> Optional[str]:
    """Из «бег 1ч Z1 шоссе» вернуть «Z1». Из «3:20 Z1-Z2» → «Z1-Z2»."""
    m = _ZONE_RE.search(text)
    if not m:
        return None
    z1 = m.group(1)
    z2 = m.group(2)
    if z2 and z2 != z1:
        return f"Z{z1}-Z{z2}"
    return f"Z{z1}"


def zone_to_set(zone: str) -> set[int]:
    """«Z1-Z2» → {1, 2}; «Z2» → {2}."""
    nums = re.findall(r"[1-5]", zone)
    if not nums:
        return set()
    if len(nums) == 1:
        return {int(nums[0])}
    a, b = int(nums[0]), int(nums[1])
    return set(range(min(a, b), max(a, b) + 1))


def load_all() -> list[PlannedSession]:
    """Прочитать весь лист «Тренировки списком»."""
    wb = openpyxl.load_workbook(config.PLAN_EXCEL, data_only=True)
    ws = wb[config.PLAN_SHEET]
    sessions: list[PlannedSession] = []

    for row in ws.iter_rows(min_row=2, values_only=True):
        if not row or row[0] is None:
            continue
        date_v, day, week, part, text, type_, hours = row[:7]
        if not date_v or not text:
            continue
        date_str = str(date_v)[:10]
        sessions.append(
            PlannedSession(
                date=date_str,
                day_short=str(day) if day else "",
                week_num=int(week) if week else 0,
                part=str(part) if part else "",
                text=str(text),
                type=str(type_) if type_ else "",
                hours=float(hours) if hours is not None else 0.0,
            )
        )
    return sessions


def for_date(d: date) -> list[PlannedSession]:
    """Все плановые сессии на дату, отсортированные утро→вечер."""
    target = d.isoformat()
    all_ = load_all()
    res = [s for s in all_ if s.date == target]
    order = {"утро": 0, "вечер": 1}
    res.sort(key=lambda s: order.get(s.part, 99))
    return res


def for_week_of(d: date) -> list[PlannedSession]:
    """Все сессии недели, в которой лежит дата (Пн-Вс)."""
    weekday = d.weekday()  # 0=Пн
    from datetime import timedelta
    start = d - timedelta(days=weekday)
    end = start + timedelta(days=6)
    all_ = load_all()
    return [s for s in all_ if start.isoformat() <= s.date <= end.isoformat()]
