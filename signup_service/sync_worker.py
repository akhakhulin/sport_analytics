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


def run() -> int:
    """Главный entrypoint. Возвращает exit-code."""
    users_db.init_schema()
    with users_db.get_conn() as c:
        rows = list(c.execute(
            "SELECT user_id, access_token_enc, refresh_token_enc, expires_at "
            "FROM connected_accounts WHERE provider='strava'"
        ).fetchall())

    if not rows:
        log.info("no strava connected_accounts — nothing to sync")
        return 0

    log.info("syncing strava for %d users", len(rows))
    ok = err = 0
    for r in rows:
        user_id = r["user_id"]
        try:
            result = _sync_one_strava(user_id, r)
            if result["status"] == "ok":
                ok += 1
                log.info(
                    "user=%s strava: pulled=%d new=%d",
                    user_id, result["pulled"], result["new"],
                )
            else:
                err += 1
                log.warning("user=%s strava: %s — %s", user_id, result["status"], result["error"])
        except Exception as e:  # noqa: BLE001
            err += 1
            log.exception("user=%s strava: unexpected error", user_id)

    log.info("sync done: ok=%d err=%d", ok, err)
    return 0 if err == 0 else 1


def main():
    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s %(levelname)s %(name)s: %(message)s",
        stream=sys.stdout,
    )
    sys.exit(run())


if __name__ == "__main__":
    main()
