"""
Облачный воркер: проходится по всем активным cloud_athletes и
синкает каждого через garmin_sync.run_for(...).

Запуск:
- по cron из GitHub Actions (.github/workflows/cloud_sync.yml)
- вручную:  `python -m cloud_sync.sync_all`
- одного:   `python -m cloud_sync.admin run <athlete_id>`

Требует переменные окружения:
    TURSO_DATABASE_URL, TURSO_AUTH_TOKEN  — куда писать
    CLOUD_MASTER_KEY                       — для расшифровки кредов
"""

from __future__ import annotations

import logging
import sys
import traceback
from datetime import datetime

from dotenv import load_dotenv
load_dotenv()

import db as dbm
import garmin_sync
from cloud_sync import crypto
from cloud_sync.db_schema import migrate


log = logging.getLogger("cloud_sync.sync_all")
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s | %(levelname)s | %(name)s | %(message)s",
)


def _open_conn():
    conn = dbm.connect()
    migrate(conn)
    return conn


def _fetch_athletes(conn, only: str | None = None):
    if only:
        rows = conn.execute(
            "SELECT athlete_id, garmin_email, password_enc, tokens_enc "
            "FROM cloud_athletes WHERE athlete_id=? AND active=1",
            (only,),
        ).fetchall()
    else:
        rows = conn.execute(
            "SELECT athlete_id, garmin_email, password_enc, tokens_enc "
            "FROM cloud_athletes WHERE active=1 "
            "ORDER BY athlete_id"
        ).fetchall()
    return rows


def _save_state(conn, athlete_id: str, *, tokens_str: str | None,
                error: str | None) -> None:
    if tokens_str:
        conn.execute(
            "UPDATE cloud_athletes SET tokens_enc=?, last_sync=?, last_error=? "
            "WHERE athlete_id=?",
            (crypto.encrypt(tokens_str), datetime.utcnow().isoformat(),
             error, athlete_id),
        )
    else:
        conn.execute(
            "UPDATE cloud_athletes SET last_sync=?, last_error=? "
            "WHERE athlete_id=?",
            (datetime.utcnow().isoformat(), error, athlete_id),
        )
    conn.commit()


def _log_run(conn, athlete_id: str, started: datetime,
             result: dict | None, error: str | None) -> None:
    conn.execute(
        "INSERT INTO sync_runs (athlete_id, started_at, finished_at, "
        "activities, daily, sleep, hrv, error) VALUES (?,?,?,?,?,?,?,?)",
        (
            athlete_id,
            started.isoformat(),
            datetime.utcnow().isoformat(),
            (result or {}).get("activities", 0),
            (result or {}).get("daily", 0),
            (result or {}).get("sleep", 0),
            (result or {}).get("hrv", 0),
            error,
        ),
    )
    conn.commit()


def _sync_one(conn, row) -> tuple[bool, str | None]:
    athlete_id, email, pwd_enc, tok_enc = row
    started = datetime.utcnow()
    log.info("=== %s ===", athlete_id)

    try:
        password = crypto.decrypt(pwd_enc)
        tokens_str = crypto.decrypt(tok_enc) if tok_enc else ""
    except Exception as exc:  # noqa: BLE001
        msg = f"decrypt failed: {exc}"
        log.error("[%s] %s", athlete_id, msg)
        _save_state(conn, athlete_id, tokens_str=None, error=msg)
        _log_run(conn, athlete_id, started, None, msg)
        return False, msg

    if not tokens_str:
        msg = "tokens пустые — нужен `cloud_sync.admin renew` для входа с 2FA"
        log.error("[%s] %s", athlete_id, msg)
        _save_state(conn, athlete_id, tokens_str=None, error=msg)
        _log_run(conn, athlete_id, started, None, msg)
        return False, msg

    try:
        result = garmin_sync.run_for(
            athlete_id=athlete_id,
            email=email,
            password=password,
            tokenstore=tokens_str,
            initial_days=365,
            conn=conn,
        )
    except Exception as exc:  # noqa: BLE001
        msg = f"{type(exc).__name__}: {exc}"
        log.error("[%s] %s\n%s", athlete_id, msg, traceback.format_exc())
        _save_state(conn, athlete_id, tokens_str=None, error=msg)
        _log_run(conn, athlete_id, started, None, msg)
        return False, msg

    _save_state(conn, athlete_id,
                tokens_str=result.get("tokens_str"),
                error=None)
    _log_run(conn, athlete_id, started, result, None)
    log.info(
        "[%s] OK: activities=%d daily=%d sleep=%d hrv=%d",
        athlete_id,
        result["activities"], result["daily"],
        result["sleep"], result["hrv"],
    )
    return True, None


def run_all() -> int:
    conn = _open_conn()
    rows = _fetch_athletes(conn)
    if not rows:
        log.info("Активных облачных атлетов нет.")
        conn.close()
        return 0

    log.info("Синкаю %d атлетов", len(rows))
    failed = 0
    for row in rows:
        ok, _ = _sync_one(conn, row)
        if not ok:
            failed += 1

    dbm.sync(conn)
    conn.close()

    if failed:
        log.warning("Завершено с ошибками: %d из %d", failed, len(rows))
        return 1
    log.info("Все %d атлетов синканы успешно.", len(rows))
    return 0


def run_one(athlete_id: str) -> int:
    conn = _open_conn()
    rows = _fetch_athletes(conn, only=athlete_id)
    if not rows:
        log.error("Атлет %s не найден или не активен.", athlete_id)
        conn.close()
        return 1
    ok, _ = _sync_one(conn, rows[0])
    dbm.sync(conn)
    conn.close()
    return 0 if ok else 1


if __name__ == "__main__":
    raise SystemExit(run_all())
