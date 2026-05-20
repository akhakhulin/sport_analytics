"""
Синхронизация данных Garmin Connect → SQLite/Turso.

Что тянем:
- activities: список тренировок + сводные метрики
- daily_stats: шаги, калории, RHR, стресс по дням
- sleep: сон (фазы, длительность, качество)
- hrv: HRV по ночам

Инкрементально: при повторном запуске догружает только новое.

Два режима использования:
1. **Локально / в .exe** — `python garmin_sync.py` (или `sync.exe`).
   Читает один атлет из .env, синкает.
2. **Облачный воркер** — импортирует `run_for(...)` из cloud_sync/sync_all.py
   и вызывает в цикле для каждого «облачного» атлета.
"""

from __future__ import annotations

import os
import sys
import json
import time
import logging
from datetime import date, datetime, timedelta
from pathlib import Path

# Если запущено как PyInstaller-onefile (.exe), CWD при двойном клике —
# это любая папка из открытого «Проводника». Нужно перейти в каталог,
# где лежит сам .exe, чтобы рядом нашёлся .env, .garminconnect/ и data/.
if getattr(sys, "frozen", False):
    os.chdir(Path(sys.executable).resolve().parent)

from dotenv import load_dotenv
from tqdm import tqdm

from garminconnect import (
    Garmin,
    GarminConnectAuthenticationError,
    GarminConnectConnectionError,
    GarminConnectTooManyRequestsError,
)

load_dotenv()

import db as dbm  # импорт после load_dotenv: db.py читает env при импорте


logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s | %(levelname)s | %(message)s",
)
log = logging.getLogger("garmin_sync")


# region БД

SCHEMA = """
CREATE TABLE IF NOT EXISTS activities (
    activity_id         INTEGER PRIMARY KEY,
    athlete_id          TEXT NOT NULL DEFAULT 'me',
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
    raw_json            TEXT,
    temp_c              REAL,
    humidity_pct        REAL,
    wind_speed_kmh      REAL
);

CREATE TABLE IF NOT EXISTS daily_stats (
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
);

CREATE TABLE IF NOT EXISTS sleep (
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
);

CREATE TABLE IF NOT EXISTS hrv (
    athlete_id          TEXT NOT NULL,
    day                 TEXT NOT NULL,
    weekly_avg          REAL,
    last_night_avg      REAL,
    status              TEXT,
    raw_json            TEXT,
    PRIMARY KEY (athlete_id, day)
);

CREATE TABLE IF NOT EXISTS user_profile (
    athlete_id              TEXT PRIMARY KEY,
    gender                  TEXT,
    birth_date              TEXT,
    height_cm               REAL,
    weight_kg               REAL,
    activity_level          INTEGER,
    vo2_max_running         REAL,
    vo2_max_cycling         REAL,
    lactate_threshold_hr    INTEGER,
    lactate_threshold_speed REAL,
    timezone                TEXT,
    measurement_system      TEXT,
    raw_json                TEXT,
    updated_at              TEXT
);

CREATE TABLE IF NOT EXISTS hr_zones (
    athlete_id          TEXT NOT NULL,
    sport               TEXT NOT NULL,    -- DEFAULT / RUNNING / CYCLING
    training_method     TEXT,
    zone1_floor         INTEGER,
    zone2_floor         INTEGER,
    zone3_floor         INTEGER,
    zone4_floor         INTEGER,
    zone5_floor         INTEGER,
    max_hr              INTEGER,
    resting_hr          INTEGER,
    lthr                INTEGER,
    raw_json            TEXT,
    updated_at          TEXT,
    PRIMARY KEY (athlete_id, sport)
);

CREATE INDEX IF NOT EXISTS idx_activities_start    ON activities(start_time_local);
CREATE INDEX IF NOT EXISTS idx_activities_type     ON activities(activity_type);
CREATE INDEX IF NOT EXISTS idx_activities_athlete  ON activities(athlete_id);
"""


def db_connect():
    conn = dbm.connect()
    # libsql Connection не имеет executescript — гоним statement по одному
    for stmt in filter(None, (s.strip() for s in SCHEMA.split(";"))):
        conn.execute(stmt)
    conn.commit()
    _ensure_weather_columns(conn)
    return conn


def _ensure_weather_columns(conn) -> None:
    """Добавляет колонки погоды в activities, если их ещё нет (миграция старых БД)."""
    cols = {r[1] for r in conn.execute("PRAGMA table_info(activities)").fetchall()}
    for col, sql_type in (
        ("temp_c", "REAL"),
        ("humidity_pct", "REAL"),
        ("wind_speed_kmh", "REAL"),
    ):
        if col not in cols:
            conn.execute(f"ALTER TABLE activities ADD COLUMN {col} {sql_type}")
    conn.commit()


def last_activity_date(conn, athlete_id: str) -> date | None:
    row = conn.execute(
        "SELECT MAX(DATE(start_time_local)) FROM activities WHERE athlete_id = ?",
        (athlete_id,),
    ).fetchone()
    if row and row[0]:
        return date.fromisoformat(row[0])
    return None


# endregion

# region Garmin client


def init_client(email: str, password: str, tokenstore: str) -> Garmin:
    """
    Логинит клиент.

    `tokenstore` — путь к директории ИЛИ строка > 512 символов с готовыми
    токенами (garth.Client.dumps()). Эта же строка возвращается из login(),
    чтобы её можно было сохранить и использовать в облаке без 2FA.
    """
    if len(tokenstore) <= 512:
        Path(tokenstore).mkdir(parents=True, exist_ok=True)
        tokenstore = str(Path(tokenstore).resolve())

    client = Garmin(email or "", password or "")
    try:
        client.login(tokenstore=tokenstore)
    except GarminConnectAuthenticationError as exc:
        msg = str(exc)
        if "Username and password are required" in msg:
            log.error(
                "Нет сохранённых токенов и не заданы GARMIN_EMAIL/PASSWORD"
            )
        else:
            log.error("Ошибка аутентификации: %s", exc)
        raise

    return client


def dump_tokens(client: Garmin) -> str:
    """Вернуть строковое представление токенов для записи в Turso."""
    return client.client.dumps()


# endregion

# region Выгрузка


def _safe(dct: dict, *keys, default=None):
    cur = dct
    for k in keys:
        if not isinstance(cur, dict) or k not in cur:
            return default
        cur = cur[k]
    return cur


def sync_activities(client: Garmin, conn, athlete_id: str, initial_days: int) -> int:
    start = 0
    batch = 100
    since = last_activity_date(conn, athlete_id)
    if since is None:
        since = date.today() - timedelta(days=initial_days)
        log.info("[%s] Первый запуск — тянем с %s", athlete_id, since)
    else:
        log.info("[%s] Последняя активность в БД: %s — тянем новее", athlete_id, since)

    total = 0
    while True:
        activities = client.get_activities(start, batch)
        if not activities:
            break

        stop = False
        for act in activities:
            raw_date = act.get("startTimeLocal", "")[:10]
            if not raw_date:
                continue
            act_date = date.fromisoformat(raw_date)
            if act_date < since:
                stop = True
                break

            conn.execute(
                """INSERT OR REPLACE INTO activities (
                    activity_id, athlete_id, start_time_local, activity_type,
                    activity_name, duration_sec, distance_m, elevation_gain_m,
                    avg_hr, max_hr, avg_speed_mps, calories,
                    training_effect_aer, training_effect_ana, vo2_max, raw_json
                ) VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)""",
                (
                    act.get("activityId"),
                    athlete_id,
                    act.get("startTimeLocal"),
                    _safe(act, "activityType", "typeKey"),
                    act.get("activityName"),
                    act.get("duration"),
                    act.get("distance"),
                    act.get("elevationGain"),
                    act.get("averageHR"),
                    act.get("maxHR"),
                    act.get("averageSpeed"),
                    act.get("calories"),
                    act.get("aerobicTrainingEffect"),
                    act.get("anaerobicTrainingEffect"),
                    act.get("vO2MaxValue"),
                    json.dumps(act, ensure_ascii=False),
                ),
            )
            total += 1

        conn.commit()
        if stop or len(activities) < batch:
            break
        start += batch

    log.info("[%s] Активностей загружено/обновлено: %d", athlete_id, total)
    return total


def _date_range(days: int) -> list[date]:
    today = date.today()
    return [today - timedelta(days=i) for i in range(days)]


def sync_daily_stats(client: Garmin, conn, athlete_id: str, days: int) -> int:
    existing = {
        r[0] for r in conn.execute(
            "SELECT day FROM daily_stats WHERE athlete_id = ?", (athlete_id,)
        ).fetchall()
    }
    todo = [d for d in _date_range(days) if d.isoformat() not in existing]
    count = 0
    for d in tqdm(todo, desc=f"daily/{athlete_id}"):
        try:
            stats = client.get_stats(d.isoformat())
        except Exception as exc:  # noqa: BLE001
            log.warning("get_stats(%s): %s", d, exc)
            continue
        if not stats:
            continue
        conn.execute(
            "INSERT OR REPLACE INTO daily_stats VALUES (?,?,?,?,?,?,?,?,?,?,?,?)",
            (
                athlete_id,
                d.isoformat(),
                stats.get("totalSteps"),
                stats.get("totalDistanceMeters"),
                stats.get("totalKilocalories"),
                stats.get("activeKilocalories"),
                stats.get("restingHeartRate"),
                stats.get("averageStressLevel"),
                stats.get("bodyBatteryHighestValue"),
                stats.get("bodyBatteryLowestValue"),
                stats.get("floorsAscended"),
                json.dumps(stats, ensure_ascii=False),
            ),
        )
        count += 1
    conn.commit()
    log.info("[%s] Дней статистики добавлено: %d", athlete_id, count)
    return count


def sync_sleep(client: Garmin, conn, athlete_id: str, days: int) -> int:
    existing = {
        r[0] for r in conn.execute(
            "SELECT day FROM sleep WHERE athlete_id = ?", (athlete_id,)
        ).fetchall()
    }
    todo = [d for d in _date_range(days) if d.isoformat() not in existing]
    count = 0
    for d in tqdm(todo, desc=f"sleep/{athlete_id}"):
        try:
            data = client.get_sleep_data(d.isoformat())
        except Exception as exc:  # noqa: BLE001
            log.warning("get_sleep_data(%s): %s", d, exc)
            continue
        daily = _safe(data, "dailySleepDTO") or {}
        if not daily:
            continue
        conn.execute(
            "INSERT OR REPLACE INTO sleep VALUES (?,?,?,?,?,?,?,?,?,?,?)",
            (
                athlete_id,
                d.isoformat(),
                daily.get("sleepStartTimestampLocal"),
                daily.get("sleepEndTimestampLocal"),
                daily.get("sleepTimeSeconds"),
                daily.get("deepSleepSeconds"),
                daily.get("lightSleepSeconds"),
                daily.get("remSleepSeconds"),
                daily.get("awakeSleepSeconds"),
                _safe(daily, "sleepScores", "overall", "value"),
                json.dumps(data, ensure_ascii=False),
            ),
        )
        count += 1
    conn.commit()
    log.info("[%s] Дней сна добавлено: %d", athlete_id, count)
    return count


def sync_user_profile(client: Garmin, conn, athlete_id: str) -> int:
    """Один раз при каждом проходе: тянет get_user_profile() и пишет в user_profile."""
    try:
        p = client.get_user_profile()
    except Exception as exc:  # noqa: BLE001
        log.warning("[%s] get_user_profile: %s", athlete_id, exc)
        return 0

    ud = (p or {}).get("userData") or {}
    weight_g = ud.get("weight")
    weight_kg = round(weight_g / 1000.0, 1) if weight_g else None

    conn.execute(
        """INSERT OR REPLACE INTO user_profile VALUES
           (?,?,?,?,?,?,?,?,?,?,?,?,?,?)""",
        (
            athlete_id,
            ud.get("gender"),
            ud.get("birthDate"),
            ud.get("height"),
            weight_kg,
            ud.get("activityLevel"),
            ud.get("vo2MaxRunning"),
            ud.get("vo2MaxCycling"),
            ud.get("lactateThresholdHeartRate"),
            ud.get("lactateThresholdSpeed"),
            None,  # timezone — приходит из userprofile_settings, добираем ниже
            ud.get("measurementSystem"),
            json.dumps(p, ensure_ascii=False),
            datetime.utcnow().isoformat(),
        ),
    )

    # Часовой пояс — отдельным запросом
    try:
        s = client.get_userprofile_settings()
        tz = (s or {}).get("timeZone")
        if tz:
            conn.execute(
                "UPDATE user_profile SET timezone = ? WHERE athlete_id = ?",
                (tz, athlete_id),
            )
    except Exception as exc:  # noqa: BLE001
        log.warning("[%s] get_userprofile_settings: %s", athlete_id, exc)

    conn.commit()
    log.info("[%s] Профиль обновлён", athlete_id)
    return 1


def sync_hr_zones(client: Garmin, conn, athlete_id: str) -> int:
    """Пишет HR-зоны атлета по всем спортам в hr_zones (DEFAULT, RUNNING, CYCLING…)."""
    try:
        zones = client.connectapi("/biometric-service/heartRateZones")
    except Exception as exc:  # noqa: BLE001
        log.warning("[%s] heartRateZones: %s", athlete_id, exc)
        return 0
    if not zones or not isinstance(zones, list):
        return 0

    now = datetime.utcnow().isoformat()
    saved = 0
    for z in zones:
        conn.execute(
            "INSERT OR REPLACE INTO hr_zones VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?)",
            (
                athlete_id,
                z.get("sport") or "DEFAULT",
                z.get("trainingMethod"),
                z.get("zone1Floor"),
                z.get("zone2Floor"),
                z.get("zone3Floor"),
                z.get("zone4Floor"),
                z.get("zone5Floor"),
                z.get("maxHeartRateUsed"),
                z.get("restingHeartRateUsed"),
                z.get("lactateThresholdHeartRateUsed"),
                json.dumps(z, ensure_ascii=False),
                now,
            ),
        )
        saved += 1
    conn.commit()
    log.info("[%s] HR-зон записано: %d", athlete_id, saved)
    return saved


def sync_weather(
    client: Garmin, conn, athlete_id: str, max_per_run: int | None = 100
) -> int:
    """Тянет температуру / влажность / скорость ветра для уличных активностей.

    Garmin возвращает погоду по ближайшей метеостанции (Imperial: °F, mph).
    Конвертируем в °C и км/ч. Тянем только то, что:
      - имеет GPS (startLatitude is not null) — комнатные тренировки пропускаем;
      - ещё не имеет сохранённой температуры.
    Чтобы не упереться в rate limit, лимитируем пакет.
    """
    _ensure_weather_columns(conn)
    rows = conn.execute(
        """SELECT activity_id, raw_json
             FROM activities
            WHERE athlete_id = ?
              AND temp_c IS NULL
              AND raw_json IS NOT NULL
            ORDER BY start_time_local DESC""",
        (athlete_id,),
    ).fetchall()

    todo: list[int] = []
    for activity_id, raw_json in rows:
        try:
            data = json.loads(raw_json) if isinstance(raw_json, str) else raw_json
        except Exception:  # noqa: BLE001
            continue
        if not isinstance(data, dict):
            continue
        if data.get("startLatitude") is None:
            continue  # нет GPS → погоды нет
        todo.append(int(activity_id))

    if max_per_run is not None:
        todo = todo[:max_per_run]
    if not todo:
        return 0

    fetched = 0
    for aid in tqdm(todo, desc=f"weather/{athlete_id}"):
        try:
            w = client.get_activity_weather(aid)
        except GarminConnectTooManyRequestsError:
            log.warning("[%s] weather: rate limit, останавливаемся", athlete_id)
            break
        except Exception as exc:  # noqa: BLE001
            log.warning("get_activity_weather(%s): %s", aid, exc)
            continue
        if not isinstance(w, dict):
            continue

        temp_f = w.get("temp")
        wind_mph = w.get("windSpeed")
        humidity = w.get("relativeHumidity")

        temp_c = (
            round((temp_f - 32) * 5 / 9, 1)
            if isinstance(temp_f, (int, float)) else None
        )
        wind_kmh = (
            round(wind_mph * 1.609344, 1)
            if isinstance(wind_mph, (int, float)) else None
        )

        # Если станция вернула совсем пусто — не пишем (повторим в след. прогоне).
        if temp_c is None and humidity is None and wind_kmh is None:
            continue

        conn.execute(
            """UPDATE activities
                  SET temp_c = ?, humidity_pct = ?, wind_speed_kmh = ?
                WHERE activity_id = ?""",
            (temp_c, humidity, wind_kmh, aid),
        )
        fetched += 1
        if fetched % 20 == 0:
            conn.commit()
        time.sleep(0.3)  # вежливо к Garmin
    conn.commit()
    log.info("[%s] Погоды добавлено: %d", athlete_id, fetched)
    return fetched


def sync_hrv(client: Garmin, conn, athlete_id: str, days: int) -> int:
    existing = {
        r[0] for r in conn.execute(
            "SELECT day FROM hrv WHERE athlete_id = ?", (athlete_id,)
        ).fetchall()
    }
    todo = [d for d in _date_range(days) if d.isoformat() not in existing]
    count = 0
    for d in tqdm(todo, desc=f"hrv/{athlete_id}"):
        try:
            data = client.get_hrv_data(d.isoformat())
        except Exception as exc:  # noqa: BLE001
            log.warning("get_hrv_data(%s): %s", d, exc)
            continue
        if not data:
            continue
        summary = data.get("hrvSummary") or {}
        conn.execute(
            "INSERT OR REPLACE INTO hrv VALUES (?,?,?,?,?,?)",
            (
                athlete_id,
                d.isoformat(),
                summary.get("weeklyAvg"),
                summary.get("lastNightAvg"),
                summary.get("status"),
                json.dumps(data, ensure_ascii=False),
            ),
        )
        count += 1
    conn.commit()
    log.info("[%s] Дней HRV добавлено: %d", athlete_id, count)
    return count


# endregion


def run_for(
    *,
    athlete_id: str,
    email: str,
    password: str,
    tokenstore: str,
    initial_days: int = 365,
    conn=None,
) -> dict:
    """
    Полный синк одного атлета. Используется и локальным main(),
    и облачным воркером (cloud_sync/sync_all.py).

    Возвращает словарь со статистикой и обновлёнными токенами:
        {
          "athlete_id": ...,
          "activities": int,
          "daily": int,
          "sleep": int,
          "hrv": int,
          "tokens_str": str | None,   # если изменились — сохрани в БД
        }

    `conn` можно передать снаружи (для воркера, который держит одно
    соединение на всех атлетов). Если None — открывается своё и закрывается.
    """
    own_conn = conn is None
    if own_conn:
        conn = db_connect()

    client = init_client(email, password, tokenstore)
    log.info("[%s] Логин OK", athlete_id)

    days_window = (
        initial_days
        if last_activity_date(conn, athlete_id) is None
        else 30
    )

    weather_max = int(os.getenv("WEATHER_MAX_PER_RUN", "100"))

    result = {
        "athlete_id": athlete_id,
        "activities": 0, "daily": 0, "sleep": 0, "hrv": 0,
        "profile": 0, "hr_zones": 0, "weather": 0,
        "tokens_str": None,
    }

    try:
        result["activities"] = sync_activities(client, conn, athlete_id, initial_days)
        result["daily"]      = sync_daily_stats(client, conn, athlete_id, days_window)
        result["sleep"]      = sync_sleep(client, conn, athlete_id, days_window)
        result["hrv"]        = sync_hrv(client, conn, athlete_id, days_window)
        result["profile"]    = sync_user_profile(client, conn, athlete_id)
        result["hr_zones"]   = sync_hr_zones(client, conn, athlete_id)
        result["weather"]    = sync_weather(client, conn, athlete_id, weather_max)
    except GarminConnectTooManyRequestsError:
        log.error("[%s] Rate limit от Garmin — попробуй позже", athlete_id)
    except GarminConnectConnectionError as exc:
        log.error("[%s] Сетевая ошибка: %s", athlete_id, exc)

    # Свежий снимок токенов — могли освежиться внутри garth
    try:
        result["tokens_str"] = dump_tokens(client)
    except Exception as exc:  # noqa: BLE001
        log.warning("[%s] Не получилось снять токены: %s", athlete_id, exc)

    if own_conn:
        dbm.sync(conn)
        conn.close()

    return result


def main() -> None:
    """Локальный режим: один атлет из .env."""
    email = os.getenv("GARMIN_EMAIL") or ""
    password = os.getenv("GARMIN_PASSWORD") or ""
    tokens_dir = os.getenv("GARMIN_TOKENS_DIR", "./.garminconnect")
    initial_days = int(os.getenv("INITIAL_HISTORY_DAYS", "365"))
    athlete = (os.getenv("ATHLETE_ID") or "me").strip()

    log.info("Backend: %s", dbm.info())
    log.info("Athlete: %s", athlete)

    try:
        run_for(
            athlete_id=athlete,
            email=email,
            password=password,
            tokenstore=tokens_dir,
            initial_days=initial_days,
        )
    except GarminConnectAuthenticationError:
        sys.exit(1)


if __name__ == "__main__":
    main()
