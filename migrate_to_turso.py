"""
Одноразовая миграция: локальная garmin.db → Turso.

Что делает:
1. Переименовывает существующий data/garmin.db → data/garmin_local_backup.db
2. Подключается к Turso через libsql (создастся свежая локальная реплика)
3. Создаёт схему
4. Переливает все строки из backup в реплику
5. sync() — пушит изменения в Turso
6. Проверяет количество строк
"""

from __future__ import annotations

import os
import shutil
import sqlite3
import sys
from pathlib import Path

from dotenv import load_dotenv

import libsql

load_dotenv()

DB_PATH = os.getenv("DB_PATH", "./data/garmin.db")
TURSO_URL = os.getenv("TURSO_DATABASE_URL", "").strip()
TURSO_TOKEN = os.getenv("TURSO_AUTH_TOKEN", "").strip()

if not (TURSO_URL and TURSO_TOKEN):
    print("ERROR: задайте TURSO_DATABASE_URL и TURSO_AUTH_TOKEN в .env")
    sys.exit(1)

local_path = Path(DB_PATH)
backup_path = local_path.with_name("garmin_local_backup.db")

SCHEMA = """
CREATE TABLE IF NOT EXISTS activities (
    activity_id         INTEGER PRIMARY KEY,
    start_time_local    TEXT,
    activity_type       TEXT,
    activity_name       TEXT,
    duration_sec        REAL,
    distance_m          REAL,
    elevation_gain_m    REAL,
    avg_hr              REAL,
    max_hr              REAL,
    avg_speed_mps       REAL,
    calories            REAL,
    training_effect_aer REAL,
    training_effect_ana REAL,
    vo2_max             REAL,
    raw_json            TEXT
);
CREATE TABLE IF NOT EXISTS daily_stats (
    day                 TEXT PRIMARY KEY,
    steps               INTEGER,
    distance_m          REAL,
    calories_total      REAL,
    calories_active     REAL,
    resting_hr          INTEGER,
    avg_stress          REAL,
    body_battery_high   INTEGER,
    body_battery_low    INTEGER,
    floors_climbed      INTEGER,
    raw_json            TEXT
);
CREATE TABLE IF NOT EXISTS sleep (
    day                 TEXT PRIMARY KEY,
    sleep_start         TEXT,
    sleep_end           TEXT,
    total_sec           INTEGER,
    deep_sec            INTEGER,
    light_sec           INTEGER,
    rem_sec             INTEGER,
    awake_sec           INTEGER,
    sleep_score         INTEGER,
    raw_json            TEXT
);
CREATE TABLE IF NOT EXISTS hrv (
    day                 TEXT PRIMARY KEY,
    weekly_avg          REAL,
    last_night_avg      REAL,
    status              TEXT,
    raw_json            TEXT
);
CREATE INDEX IF NOT EXISTS idx_activities_start ON activities(start_time_local);
CREATE INDEX IF NOT EXISTS idx_activities_type  ON activities(activity_type);
"""


def step(msg: str) -> None:
    print(f"\n--- {msg}")


def main() -> None:
    if not local_path.exists():
        print(f"ERROR: локальная БД не найдена: {local_path}")
        print("Запустите сначала `python garmin_sync.py` (без Turso) для первичной выгрузки.")
        sys.exit(1)

    step(f"Бэкап локальной БД: {local_path} -> {backup_path}")
    if backup_path.exists():
        backup_path.unlink()
    shutil.move(str(local_path), str(backup_path))

    step("Подключение к Turso (создастся свежая локальная реплика)")
    conn = libsql.connect(str(local_path), sync_url=TURSO_URL, auth_token=TURSO_TOKEN)
    conn.sync()

    step("Создание схемы в Turso")
    for stmt in filter(None, (s.strip() for s in SCHEMA.split(";"))):
        conn.execute(stmt)
    conn.commit()

    step("Чтение бэкапа и заливка в Turso")
    src = sqlite3.connect(str(backup_path))
    src.row_factory = sqlite3.Row

    tables = ["activities", "daily_stats", "sleep", "hrv"]
    for table in tables:
        rows = src.execute(f"SELECT * FROM {table}").fetchall()
        if not rows:
            print(f"  {table}: пусто")
            continue
        cols = rows[0].keys()
        placeholders = ",".join("?" * len(cols))
        col_list = ",".join(cols)
        insert = f"INSERT OR REPLACE INTO {table} ({col_list}) VALUES ({placeholders})"
        for r in rows:
            conn.execute(insert, tuple(r[c] for c in cols))
        conn.commit()
        print(f"  {table}: {len(rows)} строк")

    src.close()

    step("Push в Turso (sync)")
    conn.sync()

    step("Проверка")
    for table in tables:
        cnt = conn.execute(f"SELECT COUNT(*) FROM {table}").fetchone()[0]
        print(f"  {table}: {cnt}")

    conn.close()
    print(f"\nГотово. Бэкап оставлен: {backup_path}")
    print("Можно удалить его после проверки дашборда.")


if __name__ == "__main__":
    main()
