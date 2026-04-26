"""
Одноразовая миграция: добавляем athlete_id во все таблицы.

Что делает:
1. К таблице activities (PK = activity_id) добавляет колонку athlete_id.
2. Таблицы daily_stats / sleep / hrv пересоздаёт с композитным PK (athlete_id, day),
   данные переносит, проставляя ATHLETE_ID из .env.

Идемпотентна — повторный запуск ничего не сломает (проверяет наличие колонок).
"""

from __future__ import annotations

import os
import sys

from dotenv import load_dotenv

import db as dbm

load_dotenv()

ATHLETE = (os.getenv("ATHLETE_ID") or "me").strip()
if not ATHLETE or " " in ATHLETE:
    print("ERROR: ATHLETE_ID должен быть непустой строкой без пробелов")
    sys.exit(1)


def column_exists(conn, table: str, col: str) -> bool:
    cur = conn.execute(f"PRAGMA table_info({table})")
    return any(r[1] == col for r in cur.fetchall())


def step(msg: str) -> None:
    print(f"\n--- {msg}")


def migrate_activities(conn) -> None:
    if column_exists(conn, "activities", "athlete_id"):
        print("activities.athlete_id уже есть — пропуск")
        return
    print("activities: ADD COLUMN athlete_id")
    conn.execute(
        f"ALTER TABLE activities ADD COLUMN athlete_id TEXT NOT NULL DEFAULT '{ATHLETE}'"
    )
    conn.execute("CREATE INDEX IF NOT EXISTS idx_activities_athlete ON activities(athlete_id)")


SCHEMAS_NEW = {
    "daily_stats": """
        CREATE TABLE daily_stats (
            athlete_id          TEXT NOT NULL,
            day                 TEXT NOT NULL,
            steps               INTEGER,
            distance_m          REAL,
            calories_total      REAL,
            calories_active     REAL,
            resting_hr          INTEGER,
            avg_stress          REAL,
            body_battery_high   INTEGER,
            body_battery_low    INTEGER,
            floors_climbed      INTEGER,
            raw_json            TEXT,
            PRIMARY KEY (athlete_id, day)
        )
    """,
    "sleep": """
        CREATE TABLE sleep (
            athlete_id          TEXT NOT NULL,
            day                 TEXT NOT NULL,
            sleep_start         TEXT,
            sleep_end           TEXT,
            total_sec           INTEGER,
            deep_sec            INTEGER,
            light_sec           INTEGER,
            rem_sec             INTEGER,
            awake_sec           INTEGER,
            sleep_score         INTEGER,
            raw_json            TEXT,
            PRIMARY KEY (athlete_id, day)
        )
    """,
    "hrv": """
        CREATE TABLE hrv (
            athlete_id          TEXT NOT NULL,
            day                 TEXT NOT NULL,
            weekly_avg          REAL,
            last_night_avg      REAL,
            status              TEXT,
            raw_json            TEXT,
            PRIMARY KEY (athlete_id, day)
        )
    """,
}

# Колонки старой таблицы (без athlete_id) в порядке для INSERT
OLD_COLS = {
    "daily_stats": [
        "day", "steps", "distance_m", "calories_total", "calories_active",
        "resting_hr", "avg_stress", "body_battery_high", "body_battery_low",
        "floors_climbed", "raw_json",
    ],
    "sleep": [
        "day", "sleep_start", "sleep_end", "total_sec", "deep_sec",
        "light_sec", "rem_sec", "awake_sec", "sleep_score", "raw_json",
    ],
    "hrv": [
        "day", "weekly_avg", "last_night_avg", "status", "raw_json",
    ],
}


def migrate_daily_table(conn, table: str) -> None:
    if column_exists(conn, table, "athlete_id"):
        print(f"{table}.athlete_id уже есть — пропуск")
        return

    print(f"{table}: пересоздание с PK (athlete_id, day)")

    # Считываем старые данные
    cols = OLD_COLS[table]
    rows = conn.execute(f"SELECT {', '.join(cols)} FROM {table}").fetchall()
    print(f"  старых строк: {len(rows)}")

    conn.execute(f"DROP TABLE {table}")
    conn.execute(SCHEMAS_NEW[table].strip())

    # Заливаем с athlete_id
    placeholders = ", ".join("?" * (len(cols) + 1))
    insert_cols = "athlete_id, " + ", ".join(cols)
    sql = f"INSERT INTO {table} ({insert_cols}) VALUES ({placeholders})"
    for r in rows:
        conn.execute(sql, (ATHLETE, *r))


def main() -> None:
    print(f"Миграция multi-tenant. ATHLETE_ID для существующих данных: '{ATHLETE}'")
    print(f"Backend: {dbm.info()}")

    conn = dbm.connect()
    try:
        migrate_activities(conn)
        for t in ("daily_stats", "sleep", "hrv"):
            migrate_daily_table(conn, t)
        conn.commit()

        step("Push в Turso")
        dbm.sync(conn)

        step("Проверка")
        for t in ("activities", "daily_stats", "sleep", "hrv"):
            cnt = conn.execute(
                f"SELECT COUNT(*) FROM {t} WHERE athlete_id = ?", (ATHLETE,)
            ).fetchone()[0]
            print(f"  {t} (athlete_id={ATHLETE}): {cnt}")
    finally:
        conn.close()

    print("\nГотово. Теперь sync и dashboard работают в multi-tenant режиме.")


if __name__ == "__main__":
    main()
