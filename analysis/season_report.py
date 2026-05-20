"""
Отчёт по сезону: объём, зоны, гонки, восстановление.

Запуск:
    python -m analysis.season_report                      # последние 365 дней
    python -m analysis.season_report 2025-04-01 2026-04-26
    python -m analysis.season_report 2025-04-01 2026-04-26 akhakhulin

Считает:
- Volume by sport (часы / км / тренировки)
- Monthly breakdown
- Distribution of HR-time in Z1..Z5 (по hrTimeInZone из raw_json)
- Polarized index (Z1 / Z2-3 / Z4-5)
- Список гонок (eventType=race + по ключевым словам в названии)
- Тренды RHR / HRV / sleep / training load по месяцам
"""

from __future__ import annotations

import json
import os
import sqlite3
import sys
from datetime import date, datetime, timedelta
from pathlib import Path

import pandas as pd

ROOT = Path(__file__).resolve().parents[1]
DB_PATH = os.getenv("DB_PATH", str(ROOT / "data" / "garmin.db"))

RACE_KEYWORDS = (
    "race", "гонка", "забег", "марафон", "полумарафон", "10k", "10км",
    "чемпионат", "первенство", "kубок", "кубок", "соревнован",
)

# Какие виды считаем «лыжными»
SKI_TYPES = ("skate_skiing_ws", "cross_country_skiing_ws", "skating_ws")
RUN_TYPES = ("running", "indoor_running", "treadmill_running", "trail_running")
BIKE_TYPES = ("cycling", "indoor_cycling")
STRENGTH_TYPES = ("strength_training",)


def fmt_h(seconds: float | None) -> str:
    if not seconds:
        return "0:00"
    h = int(seconds // 3600)
    m = int((seconds % 3600) // 60)
    return f"{h}:{m:02d}"


def load_activities(start: str, end: str, athlete: str) -> pd.DataFrame:
    conn = sqlite3.connect(DB_PATH)
    df = pd.read_sql_query(
        """SELECT activity_id, start_time_local, activity_type, activity_name,
                  duration_sec, distance_m, elevation_gain_m,
                  avg_hr, max_hr, training_effect_aer, training_effect_ana,
                  vo2_max, raw_json
           FROM activities
           WHERE athlete_id = ?
             AND DATE(start_time_local) BETWEEN ? AND ?
           ORDER BY start_time_local""",
        conn, params=(athlete, start, end),
    )
    conn.close()
    if df.empty:
        return df

    # Распарсим зоны и метки из raw_json
    zone_cols = {f"z{i}_sec": [] for i in range(1, 6)}
    event_type, training_load, te_label, descriptions = [], [], [], []
    for _, row in df.iterrows():
        d = json.loads(row["raw_json"]) if row["raw_json"] else {}
        for i in range(1, 6):
            zone_cols[f"z{i}_sec"].append(d.get(f"hrTimeInZone_{i}") or 0.0)
        et = d.get("eventType") or {}
        event_type.append(et.get("typeKey") if isinstance(et, dict) else None)
        training_load.append(d.get("activityTrainingLoad"))
        te_label.append(d.get("trainingEffectLabel"))
        descriptions.append(d.get("description"))

    for k, v in zone_cols.items():
        df[k] = v
    df["event_type"] = event_type
    df["training_load"] = training_load
    df["te_label"] = te_label
    df["description"] = descriptions
    df["start"] = pd.to_datetime(df["start_time_local"])
    df["month"] = df["start"].dt.to_period("M").astype(str)
    df["week"] = df["start"].dt.to_period("W").astype(str)

    def bucket(t: str) -> str:
        if t in SKI_TYPES:
            return "ski"
        if t in RUN_TYPES:
            return "run"
        if t in BIKE_TYPES:
            return "bike"
        if t in STRENGTH_TYPES:
            return "strength"
        return "other"

    df["sport"] = df["activity_type"].apply(bucket)
    df["distance_km"] = (df["distance_m"].fillna(0) / 1000).round(1)
    df["duration_h"] = (df["duration_sec"].fillna(0) / 3600).round(2)
    return df


def section_volume_by_sport(df: pd.DataFrame) -> pd.DataFrame:
    g = df.groupby("sport").agg(
        n=("activity_id", "count"),
        hours=("duration_sec", lambda s: round(s.sum() / 3600, 1)),
        km=("distance_km", "sum"),
        avg_hr=("avg_hr", "mean"),
    ).round(1).sort_values("hours", ascending=False)
    return g


def section_monthly(df: pd.DataFrame) -> pd.DataFrame:
    pivot_h = df.pivot_table(
        index="month", columns="sport", values="duration_sec",
        aggfunc=lambda s: round(s.sum() / 3600, 1), fill_value=0,
    )
    pivot_h["TOTAL"] = pivot_h.sum(axis=1).round(1)
    return pivot_h


def section_zones_total(df: pd.DataFrame) -> pd.DataFrame:
    """Общее распределение времени по зонам (все виды)."""
    total = {f"Z{i}": df[f"z{i}_sec"].sum() for i in range(1, 6)}
    s = sum(total.values()) or 1
    out = pd.DataFrame({
        "hours": [round(total[f"Z{i}"] / 3600, 1) for i in range(1, 6)],
        "%": [round(100 * total[f"Z{i}"] / s, 1) for i in range(1, 6)],
    }, index=[f"Z{i}" for i in range(1, 6)])
    return out


def section_zones_by_sport(df: pd.DataFrame) -> pd.DataFrame:
    """Распределение зон отдельно по видам спорта (в часах)."""
    rows = []
    for sport in ("ski", "run", "bike"):
        sub = df[df["sport"] == sport]
        if sub.empty:
            continue
        z = {f"Z{i}": round(sub[f"z{i}_sec"].sum() / 3600, 1) for i in range(1, 6)}
        z["sport"] = sport
        z["total_h"] = round(sum(sub[f"z{i}_sec"].sum() for i in range(1, 6)) / 3600, 1)
        rows.append(z)
    return pd.DataFrame(rows).set_index("sport")[
        ["Z1", "Z2", "Z3", "Z4", "Z5", "total_h"]
    ]


def section_polarized_index(df: pd.DataFrame) -> dict:
    """
    Polarized: LIT (Z1+Z2) vs MIT (Z3) vs HIT (Z4+Z5).
    Идеал по Сейлеру — около 80/0/20 или 75/5/20 для подготовительного.
    """
    lit = (df["z1_sec"].sum() + df["z2_sec"].sum())
    mit = df["z3_sec"].sum()
    hit = (df["z4_sec"].sum() + df["z5_sec"].sum())
    s = lit + mit + hit or 1
    return {
        "LIT (Z1+Z2)": f"{round(100*lit/s, 1)}%  ({fmt_h(lit)})",
        "MIT (Z3)":    f"{round(100*mit/s, 1)}%  ({fmt_h(mit)})",
        "HIT (Z4+Z5)": f"{round(100*hit/s, 1)}%  ({fmt_h(hit)})",
    }


def section_races(df: pd.DataFrame) -> pd.DataFrame:
    """Гонки: eventType=race ИЛИ по ключевому слову в названии."""
    name_l = df["activity_name"].fillna("").str.lower()
    by_name = name_l.apply(lambda s: any(k in s for k in RACE_KEYWORDS))
    by_event = df["event_type"] == "race"
    races = df[by_name | by_event].copy()
    if races.empty:
        return races
    races["date"] = races["start"].dt.strftime("%Y-%m-%d")
    races["dur"] = races["duration_sec"].apply(fmt_h)
    races["pace_min_per_km"] = races.apply(
        lambda r: round(r["duration_sec"] / 60 / (r["distance_km"] or 1), 2)
        if r["distance_km"] else None, axis=1)
    races["z4+z5_min"] = ((races["z4_sec"] + races["z5_sec"]) / 60).round(0)
    return races[[
        "date", "sport", "activity_type", "activity_name",
        "distance_km", "dur", "avg_hr", "max_hr", "z4+z5_min",
        "training_load", "event_type",
    ]].sort_values("date")


def section_recovery_monthly(start: str, end: str, athlete: str) -> pd.DataFrame:
    conn = sqlite3.connect(DB_PATH)
    df = pd.read_sql_query("""
        SELECT d.day, d.resting_hr, d.avg_stress, d.body_battery_high, d.body_battery_low,
               s.total_sec/3600.0 AS sleep_h, s.sleep_score,
               h.last_night_avg AS hrv, h.status AS hrv_status
        FROM daily_stats d
        LEFT JOIN sleep s ON s.athlete_id = d.athlete_id AND s.day = d.day
        LEFT JOIN hrv   h ON h.athlete_id = d.athlete_id AND h.day = d.day
        WHERE d.athlete_id = ? AND d.day BETWEEN ? AND ?
    """, conn, params=(athlete, start, end))
    conn.close()
    if df.empty:
        return df
    df["month"] = pd.to_datetime(df["day"]).dt.to_period("M").astype(str)
    return df.groupby("month").agg(
        rhr=("resting_hr", "mean"),
        hrv=("hrv", "mean"),
        sleep_h=("sleep_h", "mean"),
        sleep_score=("sleep_score", "mean"),
        stress=("avg_stress", "mean"),
    ).round(1)


def section_training_load_monthly(df: pd.DataFrame) -> pd.DataFrame:
    return df.groupby("month").agg(
        sessions=("activity_id", "count"),
        hours=("duration_sec", lambda s: round(s.sum() / 3600, 1)),
        load_sum=("training_load", lambda s: round(s.fillna(0).sum(), 0)),
        avg_te_aer=("training_effect_aer", "mean"),
        avg_te_ana=("training_effect_ana", "mean"),
    ).round(1)


def main() -> None:
    args = sys.argv[1:]
    end = args[1] if len(args) > 1 else date.today().isoformat()
    start = args[0] if len(args) > 0 else (
        date.fromisoformat(end) - timedelta(days=365)
    ).isoformat()
    athlete = args[2] if len(args) > 2 else "akhakhulin"

    print(f"\n{'='*70}\nОтчёт: {athlete} | {start} → {end}\n{'='*70}")

    df = load_activities(start, end, athlete)
    if df.empty:
        print("Нет данных за период")
        return

    print(f"\n[1] Объём по видам спорта ({len(df)} активностей)")
    print(section_volume_by_sport(df).to_string())

    print(f"\n[2] Объём по месяцам (часы)")
    print(section_monthly(df).to_string())

    print(f"\n[3] Распределение по зонам (всё суммарно)")
    print(section_zones_total(df).to_string())

    print(f"\n[4] Зоны по видам спорта (часы)")
    z = section_zones_by_sport(df)
    if not z.empty:
        print(z.to_string())

    print(f"\n[5] Polarized index (LIT/MIT/HIT)")
    for k, v in section_polarized_index(df).items():
        print(f"  {k:14s} {v}")

    print(f"\n[6] Гонки и старты")
    races = section_races(df)
    if races.empty:
        print("  Не найдено")
    else:
        with pd.option_context("display.max_colwidth", 60, "display.width", 200):
            print(races.to_string(index=False))

    print(f"\n[7] Тренировочная нагрузка по месяцам")
    print(section_training_load_monthly(df).to_string())

    print(f"\n[8] Восстановление по месяцам (RHR / HRV / сон / стресс)")
    rec = section_recovery_monthly(start, end, athlete)
    if not rec.empty:
        print(rec.to_string())


if __name__ == "__main__":
    main()
