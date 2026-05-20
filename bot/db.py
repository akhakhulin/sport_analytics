"""БД-расширения для бота: новые таблицы + хелперы.

Использует существующий data/garmin.db (через DB_PATH).
"""
from __future__ import annotations

import sqlite3
from datetime import datetime, timedelta
from typing import Optional

from . import config


SCHEMA = """
CREATE TABLE IF NOT EXISTS bot_state (
    key TEXT PRIMARY KEY,
    value TEXT,
    updated_at TEXT
);

CREATE TABLE IF NOT EXISTS bot_messages (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    sent_at TEXT NOT NULL,
    kind TEXT NOT NULL,            -- morning / activity / command_reply
    chat_id TEXT,
    text TEXT,
    related_activity_id INTEGER,   -- если связано с активностью
    related_date TEXT              -- YYYY-MM-DD если связано с днём
);

CREATE TABLE IF NOT EXISTS training_assessment (
    activity_id INTEGER PRIMARY KEY,
    assessed_at TEXT NOT NULL,
    plan_text TEXT,                -- текст из Excel «Тренировки списком»
    plan_zone TEXT,                -- Z1, Z2, Z1-Z2 etc., NULL если не извлечено
    actual_zone_time_pct REAL,     -- % времени в плановой зоне
    matches_plan INTEGER,          -- 1 / 0 / NULL (если зона не извлечена)
    raw_assessment_json TEXT
);

CREATE TABLE IF NOT EXISTS subjective_feedback (
    activity_id INTEGER PRIMARY KEY,
    asked_at TEXT,                 -- когда бот задал вопрос (NULL = записан вручную /feel)
    answered_at TEXT,              -- когда пользователь ответил
    feeling TEXT,                  -- 'fire' / 'normal' / 'tired'
    deviation_kind TEXT,           -- 'duration_over' / 'duration_under' / 'zone_miss' / 'manual'
    deviation_pct REAL,            -- |% отклонения|
    notes TEXT
);
"""


def get_conn() -> sqlite3.Connection:
    conn = sqlite3.connect(str(config.DB_PATH), timeout=15)
    conn.row_factory = sqlite3.Row
    return conn


def init_schema() -> None:
    with get_conn() as conn:
        conn.executescript(SCHEMA)
        conn.commit()


def get_state(key: str) -> Optional[str]:
    with get_conn() as conn:
        row = conn.execute(
            "SELECT value FROM bot_state WHERE key=?", (key,)
        ).fetchone()
        return row["value"] if row else None


def set_state(key: str, value: str) -> None:
    now = datetime.utcnow().isoformat()
    with get_conn() as conn:
        conn.execute(
            "INSERT OR REPLACE INTO bot_state (key, value, updated_at) VALUES (?, ?, ?)",
            (key, value, now),
        )
        conn.commit()


def log_message(kind: str, text: str, chat_id: Optional[str] = None,
                related_activity_id: Optional[int] = None,
                related_date: Optional[str] = None) -> None:
    with get_conn() as conn:
        conn.execute(
            """INSERT INTO bot_messages
               (sent_at, kind, chat_id, text, related_activity_id, related_date)
               VALUES (?, ?, ?, ?, ?, ?)""",
            (datetime.utcnow().isoformat(), kind, chat_id, text,
             related_activity_id, related_date),
        )
        conn.commit()


def get_chat_id() -> Optional[str]:
    """Сначала из bot_state (приоритет — записан после /start), потом из env."""
    cid = get_state("chat_id")
    if cid:
        return cid
    if config.TELEGRAM_CHAT_ID_ENV:
        return config.TELEGRAM_CHAT_ID_ENV
    return None


def save_chat_id(chat_id: int | str) -> None:
    set_state("chat_id", str(chat_id))


def is_morning_sent_today(date_str: str) -> bool:
    return get_state(f"morning_sent_{date_str}") == "1"


def mark_morning_sent(date_str: str) -> None:
    set_state(f"morning_sent_{date_str}", "1")


def heartbeat() -> None:
    """Обновить отметку «бот жив». Вызывается по таймеру."""
    set_state("last_heartbeat", datetime.utcnow().isoformat())


def get_last_heartbeat() -> Optional[str]:
    return get_state("last_heartbeat")


def is_activity_assessed(activity_id: int) -> bool:
    with get_conn() as conn:
        row = conn.execute(
            "SELECT 1 FROM training_assessment WHERE activity_id=?",
            (activity_id,),
        ).fetchone()
        return row is not None


def save_assessment(activity_id: int, plan_text: Optional[str],
                    plan_zone: Optional[str], actual_pct: Optional[float],
                    matches: Optional[int], raw_json: str) -> None:
    with get_conn() as conn:
        conn.execute(
            """INSERT OR REPLACE INTO training_assessment
               (activity_id, assessed_at, plan_text, plan_zone,
                actual_zone_time_pct, matches_plan, raw_assessment_json)
               VALUES (?, ?, ?, ?, ?, ?, ?)""",
            (activity_id, datetime.utcnow().isoformat(),
             plan_text, plan_zone, actual_pct, matches, raw_json),
        )
        conn.commit()


# === Subjective feedback ===

def mark_feedback_asked(activity_id: int, deviation_kind: str,
                        deviation_pct: Optional[float]) -> None:
    """Бот задал вопрос — фиксируем, чтобы не дублировать."""
    with get_conn() as conn:
        conn.execute(
            """INSERT OR IGNORE INTO subjective_feedback
               (activity_id, asked_at, deviation_kind, deviation_pct)
               VALUES (?, ?, ?, ?)""",
            (activity_id, datetime.utcnow().isoformat(),
             deviation_kind, deviation_pct),
        )
        conn.commit()


def save_feedback(activity_id: int, feeling: str,
                  notes: Optional[str] = None) -> None:
    """Запись ответа пользователя. feeling ∈ {fire, normal, tired}.

    Если строки ещё нет (например /feel вручную) — создаёт с deviation_kind=manual.
    """
    now = datetime.utcnow().isoformat()
    with get_conn() as conn:
        existing = conn.execute(
            "SELECT 1 FROM subjective_feedback WHERE activity_id=?",
            (activity_id,),
        ).fetchone()
        if existing:
            conn.execute(
                """UPDATE subjective_feedback
                      SET feeling=?, answered_at=?, notes=COALESCE(?, notes)
                    WHERE activity_id=?""",
                (feeling, now, notes, activity_id),
            )
        else:
            conn.execute(
                """INSERT INTO subjective_feedback
                   (activity_id, answered_at, feeling, deviation_kind, notes)
                   VALUES (?, ?, ?, 'manual', ?)""",
                (activity_id, now, feeling, notes),
            )
        conn.commit()


def is_feedback_asked(activity_id: int) -> bool:
    with get_conn() as conn:
        row = conn.execute(
            "SELECT 1 FROM subjective_feedback WHERE activity_id=? AND asked_at IS NOT NULL",
            (activity_id,),
        ).fetchone()
        return row is not None


def last_unansweredable_activity(athlete_id: str, limit_hours: int = 36) -> Optional[int]:
    """Самая свежая активность за последние N часов — для команды /feel."""
    with get_conn() as conn:
        row = conn.execute(
            f"""SELECT activity_id FROM activities
                WHERE athlete_id=?
                  AND datetime(start_time_local) >= datetime('now', '-{limit_hours} hours')
                  AND duration_sec >= 600
                ORDER BY start_time_local DESC
                LIMIT 1""",
            (athlete_id,),
        ).fetchone()
        return int(row["activity_id"]) if row else None


def set_pending_text_feedback(activity_id: int, prompt_message_id: int,
                              ttl_hours: int = 6) -> None:
    """Зафиксировать «ждём текстовый фидбек».

    Текст пользователя в Telegram в течение TTL пойдёт в notes этой активности,
    если он либо явный reply на prompt_message_id, либо просто следующее
    некомандное сообщение в окне TTL.
    """
    import json as _json
    payload = {
        "activity_id": int(activity_id),
        "prompt_message_id": int(prompt_message_id),
        "expires_at": (datetime.utcnow() + timedelta(hours=ttl_hours)).isoformat(),
    }
    set_state("pending_text_feedback", _json.dumps(payload))


def get_pending_text_feedback() -> Optional[dict]:
    """Вернуть pending payload или None если истёк/нет."""
    import json as _json
    raw = get_state("pending_text_feedback")
    if not raw:
        return None
    try:
        data = _json.loads(raw)
    except Exception:
        return None
    try:
        if datetime.fromisoformat(data["expires_at"]) < datetime.utcnow():
            return None
    except Exception:
        return None
    return data


def clear_pending_text_feedback() -> None:
    set_state("pending_text_feedback", "")
