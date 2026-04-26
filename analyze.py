"""
Примеры аналитики по локальной БД Garmin.
Запуск: python analyze.py
"""

import os
from pathlib import Path

import pandas as pd
from dotenv import load_dotenv

import db as dbm

load_dotenv()
DB_PATH = os.getenv("DB_PATH", "./data/garmin.db")
ATHLETE = (os.getenv("ATHLETE_ID") or "me").strip()


def load(query: str, params: tuple = ()) -> pd.DataFrame:
    conn = dbm.connect()
    try:
        cur = conn.execute(query, params) if params else conn.execute(query)
        cols = [d[0] for d in cur.description] if cur.description else []
        rows = cur.fetchall()
        return pd.DataFrame(rows, columns=cols) if cols else pd.DataFrame()
    finally:
        conn.close()


def summary_by_type() -> pd.DataFrame:
    df = load("SELECT * FROM activities WHERE athlete_id = ?", (ATHLETE,))
    if df.empty:
        return df
    df["start"] = pd.to_datetime(df["start_time_local"])
    df["distance_km"] = df["distance_m"] / 1000
    df["duration_min"] = df["duration_sec"] / 60
    agg = (
        df.groupby("activity_type")
        .agg(
            count=("activity_id", "count"),
            total_km=("distance_km", "sum"),
            total_min=("duration_min", "sum"),
            avg_hr=("avg_hr", "mean"),
            avg_te_aer=("training_effect_aer", "mean"),
        )
        .round(1)
        .sort_values("count", ascending=False)
    )
    return agg


def weekly_volume() -> pd.DataFrame:
    df = load("SELECT * FROM activities WHERE athlete_id = ?", (ATHLETE,))
    if df.empty:
        return df
    df["start"] = pd.to_datetime(df["start_time_local"])
    df["distance_km"] = df["distance_m"] / 1000
    df["duration_min"] = df["duration_sec"] / 60
    df["week"] = df["start"].dt.to_period("W").dt.start_time
    return (
        df.groupby("week")
        .agg(
            activities=("activity_id", "count"),
            km=("distance_km", "sum"),
            minutes=("duration_min", "sum"),
        )
        .round(1)
        .tail(12)
    )


def recovery_snapshot() -> pd.DataFrame:
    """Пульс покоя + HRV + сон за последний месяц."""
    q = """
        SELECT d.day, d.resting_hr, d.avg_stress,
               s.total_sec / 3600.0 AS sleep_h, s.sleep_score,
               h.last_night_avg AS hrv
        FROM daily_stats d
        LEFT JOIN sleep s ON s.athlete_id = d.athlete_id AND s.day = d.day
        LEFT JOIN hrv   h ON h.athlete_id = d.athlete_id AND h.day = d.day
        WHERE d.athlete_id = ?
        ORDER BY d.day DESC
        LIMIT 30
    """
    return load(q, (ATHLETE,)).round(1)


def main() -> None:
    if not Path(DB_PATH).exists():
        print(f"БД не найдена: {DB_PATH}. Сначала запусти: python garmin_sync.py")
        return

    print("\n=== Активности по типам ===")
    print(summary_by_type().to_string())

    print("\n=== Объём по неделям (последние 12) ===")
    print(weekly_volume().to_string())

    print("\n=== Восстановление (30 дней) ===")
    print(recovery_snapshot().to_string(index=False))


if __name__ == "__main__":
    main()
