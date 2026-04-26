"""Схема таблицы cloud_athletes + sync_runs (логи). Создаётся миграцией."""

from __future__ import annotations

CLOUD_SCHEMA = """
CREATE TABLE IF NOT EXISTS cloud_athletes (
    athlete_id      TEXT PRIMARY KEY,
    name            TEXT,
    garmin_email    TEXT NOT NULL,
    password_enc    TEXT NOT NULL,    -- AES-GCM(пароль) base64
    tokens_enc      TEXT,              -- AES-GCM(garth токены) base64; NULL до первого логина
    last_sync       TEXT,              -- ISO timestamp последнего успешного запуска
    last_error      TEXT,              -- сообщение последней ошибки (NULL если ОК)
    active          INTEGER NOT NULL DEFAULT 1,
    created_at      TEXT NOT NULL DEFAULT (datetime('now'))
);

CREATE TABLE IF NOT EXISTS sync_runs (
    id              INTEGER PRIMARY KEY,
    athlete_id      TEXT,
    started_at      TEXT NOT NULL,
    finished_at     TEXT,
    activities      INTEGER DEFAULT 0,
    daily           INTEGER DEFAULT 0,
    sleep           INTEGER DEFAULT 0,
    hrv             INTEGER DEFAULT 0,
    error           TEXT
);

CREATE INDEX IF NOT EXISTS idx_sync_runs_started ON sync_runs(started_at);
"""


def migrate(conn) -> None:
    for stmt in filter(None, (s.strip() for s in CLOUD_SCHEMA.split(";"))):
        conn.execute(stmt)
    conn.commit()
