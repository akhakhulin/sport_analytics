"""Sync-воркер: дёргает Strava API для всех user'ов с connected_accounts.

Запускается через Task Scheduler (или вручную):
    python -m signup_service.sync_worker

Что делает:
1. Берёт все connected_accounts с provider='strava'
2. Для каждого:
   - Если access_token истёк — рефрешит через refresh_token
   - Дёргает /api/v3/athlete/activities?per_page=50
   - UPSERT в cloud_activities (UNIQUE(provider, external_id))
   - Логирует в cloud_sync_runs
3. Не падает на одной ошибке — продолжает другие user'ы

MVP: только Strava. Polar/Suunto — следующая итерация.
"""
from __future__ import annotations

import json
import logging
import os
import sys
import time
from datetime import datetime, timezone

import httpx

from . import db as users_db
from . import oauth as oauth_module
from .oauth import decrypt_token, encrypt_token

log = logging.getLogger("sync_worker")

STRAVA_API = "https://www.strava.com/api/v3"
STRAVA_TOKEN_URL = "https://www.strava.com/oauth/token"
ACTIVITIES_PER_PAGE = 200  # Strava max — оптимально для редких запросов
HTTP_TIMEOUT = 30.0
MAX_PAGES = 50  # safety: 50 × 200 = 10000 активностей за раз
RATE_LIMIT_SLEEP = 0.5  # вежливо к 200req/15min Strava limit

SUUNTO_API = "https://cloudapi.suunto.com/v2"
SUUNTO_TOKEN_URL = "https://cloudapi-oauth.suunto.com/oauth/token"

# Suunto activityId → human label (минимальный mapping; raw_json сохраняет всё)
# Source: Suunto Watches- SuuntoApp -Movescount-FIT-Activities.pdf
SUUNTO_SPORT_MAP = {
    1: "running", 2: "biking", 3: "mountain_biking", 4: "cross_country_skiing",
    5: "downhill_skiing", 6: "alpine_skiing", 7: "snowboarding", 8: "hiking",
    9: "walking", 10: "kayaking", 11: "rowing", 12: "windsurfing",
    13: "fitness", 14: "indoor", 15: "swimming", 16: "trail_running",
    17: "open_water_swimming", 18: "weight_training", 19: "yoga",
    24: "treadmill", 25: "indoor_cycling", 26: "circuit_training",
}


def _now_iso() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


def _refresh_strava_token(refresh_token: str) -> dict | None:
    """Обмен refresh_token на новую пару (access, refresh, expires_at)."""
    cid = os.getenv("STRAVA_CLIENT_ID", "").strip()
    secret = os.getenv("STRAVA_CLIENT_SECRET", "").strip()
    if not cid or not secret:
        log.error("STRAVA_CLIENT_ID/SECRET not set in env")
        return None
    payload = {
        "client_id": cid,
        "client_secret": secret,
        "grant_type": "refresh_token",
        "refresh_token": refresh_token,
    }
    try:
        r = httpx.post(STRAVA_TOKEN_URL, data=payload, timeout=HTTP_TIMEOUT)
    except httpx.HTTPError as e:
        log.error("Strava token refresh HTTP error: %s", e)
        return None
    if r.status_code >= 400:
        log.error("Strava token refresh failed: %d %s", r.status_code, r.text[:200])
        return None
    return r.json()


def _ensure_valid_token(user_id: str, row) -> str | None:
    """Возвращает живой access_token (рефрешит если истёк). None при провале."""
    now = int(time.time())
    expires_at = int(row["expires_at"] or 0)
    access = decrypt_token(row["access_token_enc"])
    if expires_at - now > 60:  # запас 60с
        return access
    # Refresh
    refresh = decrypt_token(row["refresh_token_enc"] or "")
    if not refresh:
        log.warning("user=%s strava: no refresh_token saved", user_id)
        return None
    new_tokens = _refresh_strava_token(refresh)
    if not new_tokens:
        return None
    with users_db.get_conn() as c:
        c.execute(
            """
            UPDATE connected_accounts SET
                access_token_enc = ?,
                refresh_token_enc = ?,
                expires_at = ?,
                last_refresh_at = ?
            WHERE user_id = ? AND provider = 'strava'
            """,
            (
                encrypt_token(new_tokens["access_token"]),
                encrypt_token(new_tokens.get("refresh_token", refresh)),
                int(new_tokens.get("expires_at", now + 21600)),
                _now_iso(),
                user_id,
            ),
        )
        c.commit()
    log.info("user=%s strava: token refreshed", user_id)
    return new_tokens["access_token"]


def _pull_strava_activities(access_token: str, period_days: int | None = None) -> list[dict] | None:
    """GET /athlete/activities с пагинацией и after-фильтром.
    period_days=None → вся история. Иначе — только activities младше N дней."""
    after_ts = None
    if period_days:
        from datetime import datetime, timezone, timedelta
        after_dt = datetime.now(timezone.utc) - timedelta(days=period_days)
        after_ts = int(after_dt.timestamp())
    all_activities: list[dict] = []
    page = 1
    while page <= MAX_PAGES:
        params = {"per_page": ACTIVITIES_PER_PAGE, "page": page}
        if after_ts:
            params["after"] = after_ts
        try:
            r = httpx.get(
                f"{STRAVA_API}/athlete/activities",
                headers={"Authorization": f"Bearer {access_token}"},
                params=params, timeout=HTTP_TIMEOUT,
            )
        except httpx.HTTPError as e:
            log.error("Strava activities HTTP error on page %d: %s", page, e)
            return all_activities or None
        if r.status_code == 429:
            log.warning("Strava rate-limited on page %d, stopping", page)
            break
        if r.status_code >= 400:
            log.error("Strava activities failed page %d: %d %s",
                      page, r.status_code, r.text[:200])
            return all_activities or None
        batch = r.json()
        if not batch:
            break
        all_activities.extend(batch)
        if len(batch) < ACTIVITIES_PER_PAGE:
            break
        page += 1
        time.sleep(RATE_LIMIT_SLEEP)
    if page > MAX_PAGES:
        log.warning("hit MAX_PAGES=%d safety stop", MAX_PAGES)
    return all_activities


def _upsert_activity(user_id: str, provider: str, act: dict) -> bool:
    """INSERT или UPDATE существующую. Возвращает True если запись была новой."""
    external_id = str(act.get("id", ""))
    if not external_id:
        return False

    with users_db.get_conn() as c:
        existing = c.execute(
            "SELECT id FROM cloud_activities WHERE provider=? AND external_id=?",
            (provider, external_id),
        ).fetchone()

        c.execute(
            """
            INSERT INTO cloud_activities
                (user_id, provider, external_id, name, sport_type, start_date,
                 distance_m, moving_time_s, elapsed_time_s, total_elevation_m,
                 average_hr, max_hr, average_watts, max_watts, kilojoules,
                 raw_json, synced_at)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            ON CONFLICT(provider, external_id) DO UPDATE SET
                name = excluded.name,
                sport_type = excluded.sport_type,
                start_date = excluded.start_date,
                distance_m = excluded.distance_m,
                moving_time_s = excluded.moving_time_s,
                elapsed_time_s = excluded.elapsed_time_s,
                total_elevation_m = excluded.total_elevation_m,
                average_hr = excluded.average_hr,
                max_hr = excluded.max_hr,
                average_watts = excluded.average_watts,
                max_watts = excluded.max_watts,
                kilojoules = excluded.kilojoules,
                raw_json = excluded.raw_json,
                synced_at = excluded.synced_at
            """,
            (
                user_id, provider, external_id,
                act.get("name"), act.get("sport_type") or act.get("type"),
                act.get("start_date"),
                act.get("distance"), act.get("moving_time"),
                act.get("elapsed_time"), act.get("total_elevation_gain"),
                act.get("average_heartrate"), act.get("max_heartrate"),
                act.get("average_watts"), act.get("max_watts"),
                act.get("kilojoules"),
                json.dumps(act, ensure_ascii=False),
                _now_iso(),
            ),
        )
        c.commit()
    return existing is None


def _sync_one_strava(user_id: str, conn_row) -> dict:
    """Один user, Strava. Возвращает dict со статусом для лога."""
    started = _now_iso()
    sync_id = None
    with users_db.get_conn() as c:
        cur = c.execute(
            "INSERT INTO cloud_sync_runs (user_id, provider, started_at, status) VALUES (?, 'strava', ?, 'running')",
            (user_id, started),
        )
        sync_id = cur.lastrowid
        c.commit()

    def _finish(status: str, error: str | None = None, pulled: int = 0, new: int = 0):
        with users_db.get_conn() as c:
            c.execute(
                "UPDATE cloud_sync_runs SET finished_at=?, status=?, error=?, pulled_count=?, new_count=? WHERE id=?",
                (_now_iso(), status, error, pulled, new, sync_id),
            )
            c.commit()
        return {"status": status, "error": error, "pulled": pulled, "new": new}

    access = _ensure_valid_token(user_id, conn_row)
    if not access:
        return _finish("error", "token_refresh_failed")

    # Глубина истории — из users.period_days; None = вся история
    with users_db.get_conn() as c:
        u = c.execute(
            "SELECT period_days FROM users WHERE user_id = ?", (user_id,),
        ).fetchone()
    period_days = u["period_days"] if u and u["period_days"] else None

    activities = _pull_strava_activities(access, period_days=period_days)
    if activities is None:
        return _finish("error", "activities_fetch_failed")

    pulled = len(activities)
    new_count = 0
    for act in activities:
        if _upsert_activity(user_id, "strava", act):
            new_count += 1

    return _finish("ok", pulled=pulled, new=new_count)


# =========================================================================
# ===                          SUUNTO                                  ====
# =========================================================================


def _refresh_suunto_token(refresh_token: str) -> dict | None:
    """Обмен refresh_token на новую пару через HTTP Basic auth (как exchange-code)."""
    cid = os.getenv("SUUNTO_CLIENT_ID", "").strip()
    secret = os.getenv("SUUNTO_CLIENT_SECRET", "").strip()
    if not cid or not secret:
        log.error("SUUNTO_CLIENT_ID/SECRET not set in env")
        return None
    payload = {
        "grant_type": "refresh_token",
        "refresh_token": refresh_token,
    }
    try:
        r = httpx.post(
            SUUNTO_TOKEN_URL, data=payload, auth=(cid, secret),
            timeout=HTTP_TIMEOUT,
        )
    except httpx.HTTPError as e:
        log.error("Suunto token refresh HTTP error: %s", e)
        return None
    if r.status_code >= 400:
        log.error("Suunto token refresh failed: %d %s", r.status_code, r.text[:200])
        return None
    return r.json()


def _ensure_valid_suunto_token(user_id: str, row) -> str | None:
    """access_token живой или рефрешит. None при провале."""
    now = int(time.time())
    expires_at = int(row["expires_at"] or 0)
    access = decrypt_token(row["access_token_enc"])
    if expires_at - now > 60:
        return access
    refresh = decrypt_token(row["refresh_token_enc"] or "")
    if not refresh:
        log.warning("user=%s suunto: no refresh_token saved", user_id)
        return None
    new_tokens = _refresh_suunto_token(refresh)
    if not new_tokens:
        return None
    with users_db.get_conn() as c:
        c.execute(
            """
            UPDATE connected_accounts SET
                access_token_enc = ?,
                refresh_token_enc = ?,
                expires_at = ?,
                last_refresh_at = ?
            WHERE user_id = ? AND provider = 'suunto'
            """,
            (
                encrypt_token(new_tokens["access_token"]),
                encrypt_token(new_tokens.get("refresh_token", refresh)),
                int(new_tokens.get("expires_at",
                    now + int(new_tokens.get("expires_in", 21600)))),
                _now_iso(),
                user_id,
            ),
        )
        c.commit()
    log.info("user=%s suunto: token refreshed", user_id)
    return new_tokens["access_token"]


def _pull_suunto_workouts(access_token: str,
                          period_days: int | None = None) -> list[dict] | None:
    """GET /v2/workouts. Suunto возвращает {error, payload[], metadata}.
    period_days=None → вся история; иначе since=now-period_days."""
    sub_key = (os.getenv("SUUNTO_SUBSCRIPTION_KEY") or "").strip()
    if not sub_key:
        log.error("SUUNTO_SUBSCRIPTION_KEY not set in env")
        return None

    headers = {
        "Authorization": f"Bearer {access_token}",
        "Ocp-Apim-Subscription-Key": sub_key,
    }
    params = {}
    if period_days:
        from datetime import datetime, timezone, timedelta
        since_dt = datetime.now(timezone.utc) - timedelta(days=period_days)
        # Suunto since в ms unix
        params["since"] = int(since_dt.timestamp() * 1000)

    try:
        r = httpx.get(f"{SUUNTO_API}/workouts", headers=headers,
                      params=params, timeout=HTTP_TIMEOUT)
    except httpx.HTTPError as e:
        log.error("Suunto workouts HTTP error: %s", e)
        return None
    if r.status_code >= 400:
        log.error("Suunto workouts failed: %d %s", r.status_code, r.text[:200])
        return None
    try:
        body = r.json()
    except Exception:
        log.error("Suunto workouts non-JSON: %s", r.text[:200])
        return None
    if body.get("error"):
        log.error("Suunto workouts error field: %s", body["error"])
        return None
    return body.get("payload") or []


def _upsert_suunto_activity(user_id: str, w: dict) -> bool:
    """Mapping Suunto workout JSON → cloud_activities. True если новая."""
    external_id = str(w.get("workoutKey") or w.get("workoutId") or "")
    if not external_id:
        return False

    # Suunto timestamps в ms unix → ISO UTC
    start_ms = w.get("startTime")
    start_iso = None
    if start_ms:
        start_iso = datetime.fromtimestamp(
            int(start_ms) / 1000, tz=timezone.utc
        ).isoformat()

    total_ms = w.get("totalTime")
    total_s = int(total_ms) // 1000 if total_ms else None

    sport_label = SUUNTO_SPORT_MAP.get(
        w.get("activityId"), f"suunto_{w.get('activityId')}"
    )

    with users_db.get_conn() as c:
        existing = c.execute(
            "SELECT id FROM cloud_activities WHERE provider=? AND external_id=?",
            ("suunto", external_id),
        ).fetchone()

        c.execute(
            """
            INSERT INTO cloud_activities
                (user_id, provider, external_id, name, sport_type, start_date,
                 distance_m, moving_time_s, elapsed_time_s, total_elevation_m,
                 average_hr, max_hr, average_watts, max_watts, kilojoules,
                 raw_json, synced_at)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            ON CONFLICT(provider, external_id) DO UPDATE SET
                name = excluded.name,
                sport_type = excluded.sport_type,
                start_date = excluded.start_date,
                distance_m = excluded.distance_m,
                moving_time_s = excluded.moving_time_s,
                elapsed_time_s = excluded.elapsed_time_s,
                total_elevation_m = excluded.total_elevation_m,
                average_hr = excluded.average_hr,
                max_hr = excluded.max_hr,
                average_watts = excluded.average_watts,
                max_watts = excluded.max_watts,
                kilojoules = excluded.kilojoules,
                raw_json = excluded.raw_json,
                synced_at = excluded.synced_at
            """,
            (
                user_id, "suunto", external_id,
                w.get("description") or w.get("activityName"),
                sport_label,
                start_iso,
                w.get("totalDistance"),
                total_s, total_s,
                w.get("totalAscent"),
                w.get("avgHR"), w.get("maxHR"),
                w.get("avgPower"), w.get("maxPower"),
                # kilojoules ≈ kcal × 4.184 если есть energyConsumption
                (int(w["energyConsumption"]) * 4.184
                 if w.get("energyConsumption") else None),
                json.dumps(w, ensure_ascii=False),
                _now_iso(),
            ),
        )
        c.commit()
    return existing is None


def _suunto_headers(access_token: str) -> dict:
    sub_key = (os.getenv("SUUNTO_SUBSCRIPTION_KEY") or "").strip()
    return {
        "Authorization": f"Bearer {access_token}",
        "Ocp-Apim-Subscription-Key": sub_key,
    }


def _pull_suunto_247samples(access_token: str, op: str,
                            period_days: int | None) -> list | None:
    """Generic GET /247samples/{op}?from=<unix_sec>&to=<unix_sec>.
    op ∈ {'activity', 'sleep', 'recovery'}. Suunto limit 28 дней — режем на чанки.
    Возвращает объединённый list или None при ошибке."""
    days = period_days if period_days else 28
    days = min(days, 365)  # safety
    now = int(time.time())
    end_ts = now
    out: list = []
    headers = _suunto_headers(access_token)
    while days > 0:
        chunk = min(days, 28)
        start_ts = end_ts - chunk * 86400
        url = f"{SUUNTO_API.replace('/v2','')}/247samples/{op}"
        try:
            r = httpx.get(
                url, headers=headers,
                params={"from": start_ts, "to": end_ts},
                timeout=HTTP_TIMEOUT,
            )
        except httpx.HTTPError as e:
            log.error("Suunto 247samples/%s HTTP error: %s", op, e)
            return None
        if r.status_code >= 400:
            log.error("Suunto 247samples/%s failed: %d %s",
                      op, r.status_code, r.text[:200])
            return None
        try:
            batch = r.json()
        except Exception:
            log.error("Suunto 247samples/%s non-JSON: %s", op, r.text[:200])
            return None
        if isinstance(batch, list):
            out.extend(batch)
        end_ts = start_ts
        days -= chunk
    return out


def _pull_suunto_daily_stats(access_token: str,
                             period_days: int | None) -> list | None:
    """GET /247samples/daily-activity-statistics?startdate=ISO&enddate=ISO.
    Aggregated steps + energy. Параметры ISO, не unix."""
    days = period_days if period_days else 28
    days = min(days, 365)
    from datetime import datetime, timezone, timedelta
    end_dt = datetime.now(timezone.utc).replace(microsecond=0, tzinfo=None)
    out: list = []
    headers = _suunto_headers(access_token)
    while days > 0:
        chunk = min(days, 28)
        start_dt = end_dt - timedelta(days=chunk)
        url = f"{SUUNTO_API.replace('/v2','')}/247samples/daily-activity-statistics"
        try:
            r = httpx.get(
                url, headers=headers,
                params={
                    "startdate": start_dt.strftime("%Y-%m-%dT%H:%M:%S"),
                    "enddate": end_dt.strftime("%Y-%m-%dT%H:%M:%S"),
                },
                timeout=HTTP_TIMEOUT,
            )
        except httpx.HTTPError as e:
            log.error("Suunto daily-stats HTTP error: %s", e)
            return None
        if r.status_code >= 400:
            log.error("Suunto daily-stats failed: %d %s",
                      r.status_code, r.text[:200])
            return None
        try:
            batch = r.json()
        except Exception:
            log.error("Suunto daily-stats non-JSON: %s", r.text[:200])
            return None
        if isinstance(batch, list):
            out.extend(batch)
        end_dt = start_dt
        days -= chunk
    return out


def _upsert_suunto_daily_raw(user_id: str, table: str, rec: dict) -> bool:
    """Сохраняет raw_json от Suunto 247samples в нашу daily-таблицу.
    table ∈ {'daily_stats','sleep','hrv'}. Уникальность по (athlete_id, day).
    Day извлекается из record (через date-fields или date_start). Если нет
    даты — кладём с day=today как fallback (но логируем warning)."""
    # Suunto 247samples records обычно содержат timestamp поля типа
    # 'Date', 'startTime', 'localStartTime' и т.д. — берём первое доступное.
    candidates = (
        rec.get("Date") or rec.get("date") or
        rec.get("startTime") or rec.get("localStartTime") or
        rec.get("LocalStartTime")
    )
    if isinstance(candidates, (int, float)):
        # unix ms
        day_iso = datetime.fromtimestamp(
            int(candidates) / 1000, tz=timezone.utc
        ).date().isoformat()
    elif isinstance(candidates, str):
        day_iso = candidates[:10]
    else:
        day_iso = datetime.now(timezone.utc).date().isoformat()
        log.warning("user=%s %s: no date field in rec, keys=%s",
                    user_id, table, list(rec.keys())[:8])

    with users_db.get_conn() as c:
        existing = c.execute(
            f"SELECT 1 FROM {table} WHERE athlete_id=? AND day=?",
            (user_id, day_iso),
        ).fetchone()
        # raw_json + минимум полей — остальные парсим когда увидим непустой
        # реальный response
        if table == "daily_stats":
            c.execute(
                """INSERT INTO daily_stats (athlete_id, day, raw_json)
                   VALUES (?, ?, ?)
                   ON CONFLICT(athlete_id, day) DO UPDATE SET
                     raw_json = excluded.raw_json""",
                (user_id, day_iso, json.dumps(rec, ensure_ascii=False)),
            )
        elif table == "sleep":
            c.execute(
                """INSERT INTO sleep (athlete_id, day, raw_json)
                   VALUES (?, ?, ?)
                   ON CONFLICT(athlete_id, day) DO UPDATE SET
                     raw_json = excluded.raw_json""",
                (user_id, day_iso, json.dumps(rec, ensure_ascii=False)),
            )
        elif table == "hrv":
            c.execute(
                """INSERT INTO hrv (athlete_id, day, raw_json)
                   VALUES (?, ?, ?)
                   ON CONFLICT(athlete_id, day) DO UPDATE SET
                     raw_json = excluded.raw_json""",
                (user_id, day_iso, json.dumps(rec, ensure_ascii=False)),
            )
        c.commit()
    return existing is None


def _sync_one_suunto(user_id: str, conn_row) -> dict:
    """Один user, Suunto. Pull: workouts + daily-stats + sleep + recovery."""
    started = _now_iso()
    with users_db.get_conn() as c:
        cur = c.execute(
            "INSERT INTO cloud_sync_runs (user_id, provider, started_at, status) "
            "VALUES (?, 'suunto', ?, 'running')",
            (user_id, started),
        )
        sync_id = cur.lastrowid
        c.commit()

    def _finish(status: str, error: str | None = None,
                pulled: int = 0, new: int = 0):
        with users_db.get_conn() as c:
            c.execute(
                "UPDATE cloud_sync_runs SET finished_at=?, status=?, error=?, "
                "pulled_count=?, new_count=? WHERE id=?",
                (_now_iso(), status, error, pulled, new, sync_id),
            )
            c.commit()
        return {"status": status, "error": error, "pulled": pulled, "new": new}

    access = _ensure_valid_suunto_token(user_id, conn_row)
    if not access:
        return _finish("error", "token_refresh_failed")

    with users_db.get_conn() as c:
        u = c.execute(
            "SELECT period_days FROM users WHERE user_id = ?", (user_id,),
        ).fetchone()
    period_days = u["period_days"] if u and u["period_days"] else None

    # 1) Workouts
    workouts = _pull_suunto_workouts(access, period_days=period_days)
    if workouts is None:
        return _finish("error", "workouts_fetch_failed")
    pulled = len(workouts)
    new_count = 0
    for w in workouts:
        try:
            if _upsert_suunto_activity(user_id, w):
                new_count += 1
        except Exception:  # noqa: BLE001
            log.exception("user=%s suunto workout upsert failed for %s",
                          user_id, w.get("workoutKey"))

    # 2) Daily stats (aggregated steps + energy, ISO date params)
    daily_stats = _pull_suunto_daily_stats(access, period_days=period_days)
    if daily_stats:
        for rec in daily_stats:
            try:
                if _upsert_suunto_daily_raw(user_id, "daily_stats", rec):
                    new_count += 1
                pulled += 1
            except Exception:  # noqa: BLE001
                log.exception("user=%s suunto daily-stats upsert failed",
                              user_id)

    # 3) Sleep (unix sec params)
    sleeps = _pull_suunto_247samples(access, "sleep",
                                     period_days=period_days)
    if sleeps:
        for rec in sleeps:
            try:
                if _upsert_suunto_daily_raw(user_id, "sleep", rec):
                    new_count += 1
                pulled += 1
            except Exception:  # noqa: BLE001
                log.exception("user=%s suunto sleep upsert failed", user_id)

    # 4) Recovery (→ таблица hrv: содержит HRV-related данные)
    recoveries = _pull_suunto_247samples(access, "recovery",
                                         period_days=period_days)
    if recoveries:
        for rec in recoveries:
            try:
                if _upsert_suunto_daily_raw(user_id, "hrv", rec):
                    new_count += 1
                pulled += 1
            except Exception:  # noqa: BLE001
                log.exception("user=%s suunto recovery upsert failed",
                              user_id)

    return _finish("ok", pulled=pulled, new=new_count)


def _sync_provider(provider: str) -> tuple[int, int]:
    """Generic loop по всем user'ам провайдера. Возвращает (ok, err)."""
    sync_fn = {
        "strava": _sync_one_strava,
        "suunto": _sync_one_suunto,
    }.get(provider)
    if not sync_fn:
        log.warning("sync для provider=%s не реализован", provider)
        return 0, 0

    with users_db.get_conn() as c:
        rows = list(c.execute(
            "SELECT user_id, access_token_enc, refresh_token_enc, expires_at "
            "FROM connected_accounts WHERE provider = ?",
            (provider,),
        ).fetchall())

    if not rows:
        log.info("%s: нет connected_accounts — пропускаю", provider)
        return 0, 0

    log.info("%s: syncing %d users", provider, len(rows))
    ok = err = 0
    for r in rows:
        user_id = r["user_id"]
        try:
            result = sync_fn(user_id, r)
            if result["status"] == "ok":
                ok += 1
                log.info("user=%s %s: pulled=%d new=%d",
                         user_id, provider, result["pulled"], result["new"])
            else:
                err += 1
                log.warning("user=%s %s: %s — %s",
                            user_id, provider, result["status"], result["error"])
        except Exception:  # noqa: BLE001
            err += 1
            log.exception("user=%s %s: unexpected error", user_id, provider)
    return ok, err


def run() -> int:
    """Главный entrypoint. Возвращает exit-code.

    Синкает Strava и Suunto. На каждого user'а по провайдеру отдельный run.
    Один error в одном user'е не валит весь sync."""
    users_db.init_schema()
    total_ok = total_err = 0
    for provider in ("strava", "suunto"):
        ok, err = _sync_provider(provider)
        total_ok += ok
        total_err += err
    log.info("sync done: ok=%d err=%d", total_ok, total_err)
    return 0 if total_err == 0 else 1


def main():
    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s %(levelname)s %(name)s: %(message)s",
        stream=sys.stdout,
    )
    sys.exit(run())


if __name__ == "__main__":
    main()
