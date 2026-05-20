"""
Одноразовый импорт активностей dmitriy_andriyanov из Garmin DataExport
архива в локальную БД и Turso.

Источник: docs/ff0576a1-.../DI_CONNECT/DI-Connect-Fitness/*_summarizedActivities.json
Период: с 2024-01-01 (всё что раньше — пропускаем).
Формат полей в архиве:
  - activityId (int) → activity_id
  - name → activity_name
  - activityType (str, e.g. "running") → activity_type
  - startTimeLocal (timestamp ms) → ISO string "YYYY-MM-DD HH:MM:SS"
  - duration (ms) → duration_sec (/1000)
  - distance (cm) → distance_m (/100)
  - elevationGain (cm) → elevation_gain_m (/100)
  - avgHr/maxHr → avg_hr/max_hr
  - avgSpeed (m/s) → avg_speed_mps
  - calories
  - aerobicTrainingEffect → training_effect_aer
  - anaerobicTrainingEffect → training_effect_ana
  - vO2MaxValue → vo2_max
  - весь dict → raw_json
"""

from __future__ import annotations

import json
import os
import sqlite3
import sys
from datetime import datetime, date, timezone
from glob import glob
from pathlib import Path

ATHLETE = "dmitriy_andriyanov"
CUTOFF_DATE = date(2024, 1, 1)
ARCHIVE_DIR = Path(
    "docs/ff0576a1-a790-4b38-b5b4-f69a8bc1222f_1 (1)/"
    "DI_CONNECT/DI-Connect-Fitness"
)


def _ts_ms_to_iso(ts_ms: float | None) -> str | None:
    if ts_ms is None:
        return None
    dt = datetime.fromtimestamp(ts_ms / 1000)
    return dt.strftime("%Y-%m-%d %H:%M:%S")


def _safe_div(v, d):
    return v / d if v is not None else None


def _map_record(act: dict, athlete_id: str) -> tuple:
    """Преобразовать запись из summarizedActivitiesExport в кортеж под INSERT."""
    raw = json.dumps(act, ensure_ascii=False)
    return (
        act.get("activityId"),                                   # activity_id
        athlete_id,                                              # athlete_id
        _ts_ms_to_iso(act.get("startTimeLocal")),                # start_time_local
        act.get("activityType"),                                 # activity_type
        act.get("name"),                                         # activity_name
        _safe_div(act.get("duration"), 1000.0),                  # duration_sec
        _safe_div(act.get("distance"), 100.0),                   # distance_m
        _safe_div(act.get("elevationGain"), 100.0),              # elevation_gain_m
        act.get("avgHr"),                                        # avg_hr
        act.get("maxHr"),                                        # max_hr
        act.get("avgSpeed"),                                     # avg_speed_mps
        act.get("calories"),                                     # calories
        act.get("aerobicTrainingEffect"),                        # training_effect_aer
        act.get("anaerobicTrainingEffect"),                      # training_effect_ana
        act.get("vO2MaxValue"),                                  # vo2_max
        raw,                                                     # raw_json
    )


def main() -> None:
    files = sorted(glob(str(ARCHIVE_DIR / "*_summarizedActivities.json")))
    print(f"Found {len(files)} JSON files in archive:")
    for f in files:
        print(f"  - {Path(f).name}")

    all_acts: list[dict] = []
    for fp in files:
        with open(fp, "r", encoding="utf-8") as f:
            data = json.load(f)
        if isinstance(data, list) and data:
            sa = data[0].get("summarizedActivitiesExport", [])
            all_acts.extend(sa)
    print(f"\nTotal activities in archive: {len(all_acts)}")

    # Фильтр по дате
    filtered = []
    for a in all_acts:
        ts = a.get("startTimeLocal")
        if ts is None:
            continue
        d = datetime.fromtimestamp(ts / 1000).date()
        if d >= CUTOFF_DATE:
            filtered.append(a)
    print(f"After cutoff {CUTOFF_DATE}: {len(filtered)} activities")
    if filtered:
        dates = [datetime.fromtimestamp(a["startTimeLocal"]/1000).date()
                 for a in filtered]
        print(f"  range: {min(dates)} -> {max(dates)}")

    # Вставляем в локальную БД
    print(f"\n--- Local DB (data/garmin.db) ---")
    loc = sqlite3.connect("data/garmin.db")
    loc_cur = loc.cursor()
    loc_cur.execute(
        "SELECT activity_id FROM activities WHERE athlete_id=?", (ATHLETE,)
    )
    existing_local = {r[0] for r in loc_cur.fetchall()}
    print(f"existing local activities for {ATHLETE}: {len(existing_local)}")

    insert_sql = (
        "INSERT OR IGNORE INTO activities ("
        "activity_id, athlete_id, start_time_local, activity_type, "
        "activity_name, duration_sec, distance_m, elevation_gain_m, "
        "avg_hr, max_hr, avg_speed_mps, calories, "
        "training_effect_aer, training_effect_ana, vo2_max, raw_json"
        ") VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)"
    )

    inserted_local = 0
    for a in filtered:
        if a.get("activityId") in existing_local:
            continue
        loc_cur.execute(insert_sql, _map_record(a, ATHLETE))
        inserted_local += 1
    loc.commit()
    print(f"inserted into local: {inserted_local}")

    loc_cur.execute(
        "SELECT COUNT(*), MIN(start_time_local), MAX(start_time_local) "
        "FROM activities WHERE athlete_id=?", (ATHLETE,)
    )
    n, mn, mx = loc_cur.fetchone()
    print(f"local now: {n} acts, {mn[:10] if mn else '-'} -> {mx[:10] if mx else '-'}")
    loc.close()

    # Turso
    print(f"\n--- Turso (production) ---")
    # Креды из .env.bak (TURSO в .env закомментирован)
    bak = Path(".env.bak")
    if bak.exists():
        for line in bak.read_text(encoding="utf-8").splitlines():
            line = line.strip()
            if not line or line.startswith("#") or "=" not in line:
                continue
            k, v = line.split("=", 1)
            if k.strip().startswith("TURSO_"):
                os.environ[k.strip()] = v.strip()
    if "TURSO_DATABASE_URL" not in os.environ:
        print("TURSO creds not found, skipping Turso")
        return

    import libsql
    turso = libsql.connect(
        "turso_remote_dmitriy.db",
        sync_url=os.environ["TURSO_DATABASE_URL"],
        auth_token=os.environ["TURSO_AUTH_TOKEN"],
    )
    turso.sync()
    tc = turso.cursor()
    tc.execute("SELECT activity_id FROM activities WHERE athlete_id=?", (ATHLETE,))
    existing_turso = {r[0] for r in tc.fetchall()}
    print(f"existing turso activities for {ATHLETE}: {len(existing_turso)}")

    inserted_turso = 0
    for a in filtered:
        if a.get("activityId") in existing_turso:
            continue
        tc.execute(insert_sql, _map_record(a, ATHLETE))
        inserted_turso += 1
    turso.commit()
    turso.sync()
    print(f"inserted into turso: {inserted_turso}")

    tc.execute(
        "SELECT COUNT(*), MIN(start_time_local), MAX(start_time_local) "
        "FROM activities WHERE athlete_id=?", (ATHLETE,)
    )
    n, mn, mx = tc.fetchone()
    print(f"turso now: {n} acts, {mn[:10] if mn else '-'} -> {mx[:10] if mx else '-'}")


if __name__ == "__main__":
    main()
