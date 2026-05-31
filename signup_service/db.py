"""Доступ к users-таблице в data/garmin.db.

Таблица users — отдельная от cloud_athletes. cloud_athletes хранит
OAuth-токены для синка с Garmin (привязывается ПОСЛЕ создания user).
"""
from __future__ import annotations

import sqlite3
import uuid
from datetime import datetime, timezone
from pathlib import Path

import bcrypt

DB_PATH = Path(__file__).resolve().parent.parent / "data" / "garmin.db"


def get_conn() -> sqlite3.Connection:
    conn = sqlite3.connect(str(DB_PATH))
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA foreign_keys = ON")
    return conn


def init_schema() -> None:
    """Создаёт таблицы users + coach_invitations + connected_accounts. Идемпотентно."""
    with get_conn() as c:
        c.execute(
            """
            CREATE TABLE IF NOT EXISTS users (
                user_id           TEXT PRIMARY KEY,
                email             TEXT UNIQUE NOT NULL,
                password_hash     TEXT NOT NULL,
                name              TEXT,
                role              TEXT NOT NULL DEFAULT 'athlete',  -- 'athlete' | 'coach'
                coach_user_id     TEXT,                              -- к какому тренеру привязан атлет
                created_at        TEXT NOT NULL,
                last_login_at     TEXT,
                email_verified_at TEXT,
                athlete_id        TEXT,
                period_days       INTEGER
            )
            """
        )
        c.execute("CREATE INDEX IF NOT EXISTS idx_users_email ON users(email)")

        # Миграция: если у старой БД нет колонок role/coach_user_id/auth_method —
        # добавим ДО создания индекса на coach_user_id
        cols = {r["name"] for r in c.execute("PRAGMA table_info(users)").fetchall()}
        if "role" not in cols:
            c.execute("ALTER TABLE users ADD COLUMN role TEXT NOT NULL DEFAULT 'athlete'")
        if "coach_user_id" not in cols:
            c.execute("ALTER TABLE users ADD COLUMN coach_user_id TEXT")
        if "auth_method" not in cols:
            # 'email' (создан через signup-форму) | 'google' (через OAuth Google)
            c.execute("ALTER TABLE users ADD COLUMN auth_method TEXT NOT NULL DEFAULT 'email'")

        c.execute("CREATE INDEX IF NOT EXISTS idx_users_coach ON users(coach_user_id)")

        # Реферальные приглашения от тренера к атлету
        c.execute(
            """
            CREATE TABLE IF NOT EXISTS coach_invitations (
                invitation_token TEXT PRIMARY KEY,
                coach_user_id    TEXT NOT NULL,
                invited_email    TEXT,
                note             TEXT,
                created_at       TEXT NOT NULL,
                expires_at       TEXT,
                used_by_user_id  TEXT,
                used_at          TEXT
            )
            """
        )
        c.execute("CREATE INDEX IF NOT EXISTS idx_invites_coach ON coach_invitations(coach_user_id)")

        # OAuth токены для подключённых внешних аккаунтов
        c.execute(
            """
            CREATE TABLE IF NOT EXISTS connected_accounts (
                id                 INTEGER PRIMARY KEY AUTOINCREMENT,
                user_id            TEXT NOT NULL,
                provider           TEXT NOT NULL,    -- 'strava','polar','suunto','garmin'
                external_user_id   TEXT,
                access_token_enc   TEXT NOT NULL,
                refresh_token_enc  TEXT,
                expires_at         INTEGER,
                scope              TEXT,
                connected_at       TEXT NOT NULL,
                last_refresh_at    TEXT,
                UNIQUE(user_id, provider)
            )
            """
        )
        c.execute("CREATE INDEX IF NOT EXISTS idx_conn_user ON connected_accounts(user_id)")

        # Активности из cloud-источников (Strava/Polar/Suunto/Garmin OAuth).
        # Отдельная таблица от существующей "activities" (которая для прямого
        # garmin-sync через garminconnect-py с auth-tokens).
        c.execute(
            """
            CREATE TABLE IF NOT EXISTS cloud_activities (
                id                   INTEGER PRIMARY KEY AUTOINCREMENT,
                user_id              TEXT NOT NULL,
                provider             TEXT NOT NULL,
                external_id          TEXT NOT NULL,
                name                 TEXT,
                sport_type           TEXT,
                start_date           TEXT,
                distance_m           REAL,
                moving_time_s        INTEGER,
                elapsed_time_s       INTEGER,
                total_elevation_m    REAL,
                average_hr           REAL,
                max_hr               REAL,
                average_watts        REAL,
                max_watts            REAL,
                kilojoules           REAL,
                raw_json             TEXT,
                synced_at            TEXT NOT NULL,
                UNIQUE(provider, external_id)
            )
            """
        )
        c.execute("CREATE INDEX IF NOT EXISTS idx_ca_user ON cloud_activities(user_id, start_date DESC)")
        c.execute("CREATE INDEX IF NOT EXISTS idx_ca_provider ON cloud_activities(provider, external_id)")

        # Sync runs log — для дебага и UI "когда последний раз дёргали"
        c.execute(
            """
            CREATE TABLE IF NOT EXISTS cloud_sync_runs (
                id           INTEGER PRIMARY KEY AUTOINCREMENT,
                user_id      TEXT NOT NULL,
                provider     TEXT NOT NULL,
                started_at   TEXT NOT NULL,
                finished_at  TEXT,
                status       TEXT,           -- 'ok' | 'token_refreshed' | 'error'
                error        TEXT,
                pulled_count INTEGER DEFAULT 0,
                new_count    INTEGER DEFAULT 0
            )
            """
        )
        c.execute("CREATE INDEX IF NOT EXISTS idx_csr_user ON cloud_sync_runs(user_id, started_at DESC)")

        # Одноразовые токены для password reset / email verify
        c.execute(
            """
            CREATE TABLE IF NOT EXISTS auth_tokens (
                token       TEXT PRIMARY KEY,
                user_id     TEXT NOT NULL,
                purpose     TEXT NOT NULL,           -- 'password_reset' | 'email_verify'
                created_at  TEXT NOT NULL,
                expires_at  TEXT NOT NULL,
                used_at     TEXT
            )
            """
        )
        c.execute("CREATE INDEX IF NOT EXISTS idx_at_user ON auth_tokens(user_id, purpose)")

        # Notify-list: «уведомить когда подключим Garmin/COROS/...»
        c.execute(
            """
            CREATE TABLE IF NOT EXISTS notify_list (
                id           INTEGER PRIMARY KEY AUTOINCREMENT,
                user_id      TEXT,
                email        TEXT NOT NULL,
                provider     TEXT NOT NULL,
                requested_at TEXT NOT NULL,
                notified_at  TEXT,
                UNIQUE(email, provider)
            )
            """
        )
        c.execute("CREATE INDEX IF NOT EXISTS idx_notify_provider ON notify_list(provider, notified_at)")
        c.commit()


def request_provider_notify(email: str, provider: str,
                             user_id: str | None = None) -> str:
    """Регистрирует email в notify-list. Возвращает: created / already / invalid."""
    email_norm = (email or "").strip().lower()
    if "@" not in email_norm or len(email_norm) < 5:
        return "invalid"
    with get_conn() as c:
        cur = c.execute(
            "INSERT OR IGNORE INTO notify_list "
            "(user_id, email, provider, requested_at) VALUES (?, ?, ?, ?)",
            (user_id, email_norm, provider, _now_iso()),
        )
        c.commit()
        return "created" if cur.rowcount > 0 else "already"


# === Auth tokens (password reset / email verify) ===

def create_auth_token(user_id: str, purpose: str, ttl_hours: int) -> str:
    """Создаёт одноразовый токен. Возвращает значение токена."""
    import secrets as _secrets
    from datetime import timedelta
    token = _secrets.token_urlsafe(24)
    expires = (datetime.now(timezone.utc) + timedelta(hours=ttl_hours)).isoformat(timespec="seconds")
    with get_conn() as c:
        c.execute(
            "INSERT INTO auth_tokens (token, user_id, purpose, created_at, expires_at) "
            "VALUES (?, ?, ?, ?, ?)",
            (token, user_id, purpose, _now_iso(), expires),
        )
        c.commit()
    return token


def find_auth_token(token: str, purpose: str) -> sqlite3.Row | None:
    """Возвращает токен если он валидный (существует, не использован, не истёк)."""
    now = _now_iso()
    with get_conn() as c:
        return c.execute(
            "SELECT * FROM auth_tokens WHERE token = ? AND purpose = ? "
            "AND used_at IS NULL AND expires_at > ?",
            (token, purpose, now),
        ).fetchone()


def consume_auth_token(token: str) -> None:
    with get_conn() as c:
        c.execute("UPDATE auth_tokens SET used_at = ? WHERE token = ?",
                  (_now_iso(), token))
        c.commit()


def update_password(user_id: str, new_password: str) -> None:
    pw_hash = bcrypt.hashpw(new_password.encode("utf-8"), bcrypt.gensalt()).decode("utf-8")
    with get_conn() as c:
        c.execute("UPDATE users SET password_hash = ? WHERE user_id = ?",
                  (pw_hash, user_id))
        c.commit()


def mark_email_verified(user_id: str) -> None:
    with get_conn() as c:
        c.execute("UPDATE users SET email_verified_at = ? WHERE user_id = ?",
                  (_now_iso(), user_id))
        c.commit()


def _now_iso() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


def create_user(
    email: str,
    password: str,
    name: str | None = None,
    role: str = "athlete",
    coach_user_id: str | None = None,
    auth_method: str = "email",
) -> str:
    """Хэширует пароль и создаёт user. Возвращает user_id.
    auth_method: 'email' (signup-форма) или 'google' (OAuth)."""
    if role not in ("athlete", "coach"):
        role = "athlete"
    if auth_method not in ("email", "google"):
        auth_method = "email"
    user_id = str(uuid.uuid4())
    pw_hash = bcrypt.hashpw(password.encode("utf-8"), bcrypt.gensalt()).decode("utf-8")
    name_clean = (name or "").strip() or None
    with get_conn() as c:
        c.execute(
            """
            INSERT INTO users (user_id, email, password_hash, name, role,
                               coach_user_id, auth_method, created_at)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (user_id, email.lower().strip(), pw_hash, name_clean, role,
             coach_user_id, auth_method, _now_iso()),
        )
        c.commit()
    return user_id


# === Приглашения от тренера ===

def create_invitation(coach_user_id: str, invited_email: str | None = None,
                      note: str | None = None, ttl_days: int = 30) -> str:
    """Создаёт invitation-token. Возвращает токен (URL-safe строка)."""
    import secrets as _secrets
    from datetime import timedelta
    token = _secrets.token_urlsafe(16)
    expires = (datetime.now(timezone.utc) + timedelta(days=ttl_days)).isoformat(timespec="seconds")
    with get_conn() as c:
        c.execute(
            """
            INSERT INTO coach_invitations
                (invitation_token, coach_user_id, invited_email, note,
                 created_at, expires_at)
            VALUES (?, ?, ?, ?, ?, ?)
            """,
            (token, coach_user_id,
             (invited_email or "").strip().lower() or None,
             (note or "").strip() or None,
             _now_iso(), expires),
        )
        c.commit()
    return token


def find_invitation(token: str) -> sqlite3.Row | None:
    """Ищет приглашение по токену вместе с именем тренера."""
    with get_conn() as c:
        return c.execute(
            """
            SELECT i.*, u.name AS coach_name, u.email AS coach_email
            FROM coach_invitations i
            JOIN users u ON u.user_id = i.coach_user_id
            WHERE i.invitation_token = ?
            """,
            (token,),
        ).fetchone()


def consume_invitation(token: str, used_by_user_id: str) -> None:
    """Помечает приглашение как использованное."""
    with get_conn() as c:
        c.execute(
            "UPDATE coach_invitations SET used_by_user_id = ?, used_at = ? "
            "WHERE invitation_token = ? AND used_by_user_id IS NULL",
            (used_by_user_id, _now_iso(), token),
        )
        c.commit()


def list_invitations_for_coach(coach_user_id: str) -> list[sqlite3.Row]:
    with get_conn() as c:
        return list(c.execute(
            """
            SELECT i.*, u.name AS used_by_name, u.email AS used_by_email
            FROM coach_invitations i
            LEFT JOIN users u ON u.user_id = i.used_by_user_id
            WHERE i.coach_user_id = ?
            ORDER BY i.created_at DESC
            """,
            (coach_user_id,),
        ).fetchall())


def list_athletes_for_coach(coach_user_id: str) -> list[sqlite3.Row]:
    with get_conn() as c:
        return list(c.execute(
            "SELECT user_id, email, name, created_at FROM users "
            "WHERE coach_user_id = ? ORDER BY created_at DESC",
            (coach_user_id,),
        ).fetchall())


def find_user_by_email(email: str) -> sqlite3.Row | None:
    with get_conn() as c:
        return c.execute(
            "SELECT * FROM users WHERE email = ?", (email.lower().strip(),)
        ).fetchone()


def find_user_by_id(user_id: str) -> sqlite3.Row | None:
    with get_conn() as c:
        return c.execute("SELECT * FROM users WHERE user_id = ?", (user_id,)).fetchone()


def verify_password(plain: str, pw_hash: str) -> bool:
    try:
        return bcrypt.checkpw(plain.encode("utf-8"), pw_hash.encode("utf-8"))
    except (ValueError, TypeError):
        return False


def touch_last_login(user_id: str) -> None:
    with get_conn() as c:
        c.execute(
            "UPDATE users SET last_login_at = ? WHERE user_id = ?",
            (_now_iso(), user_id),
        )
        c.commit()


def set_period_days(user_id: str, period_days: int | None) -> None:
    """period_days = None означает «вся история»."""
    with get_conn() as c:
        c.execute(
            "UPDATE users SET period_days = ? WHERE user_id = ?", (period_days, user_id)
        )
        c.commit()


# === connected_accounts: список + отключение ===

def list_connected_accounts(user_id: str) -> list[sqlite3.Row]:
    """Возвращает все провайдеры, к которым этот user привязан."""
    with get_conn() as c:
        return list(c.execute(
            """
            SELECT provider, external_user_id, expires_at, scope,
                   connected_at, last_refresh_at
            FROM connected_accounts
            WHERE user_id = ?
            ORDER BY connected_at DESC
            """,
            (user_id,),
        ).fetchall())


def get_connected_providers(user_id: str) -> set[str]:
    """Множество имён провайдеров, к которым user уже подключён."""
    with get_conn() as c:
        rows = c.execute(
            "SELECT provider FROM connected_accounts WHERE user_id = ?",
            (user_id,),
        ).fetchall()
    return {r["provider"] for r in rows}


def delete_connected_account(user_id: str, provider: str) -> bool:
    """Отключает провайдера. Возвращает True если что-то удалили."""
    with get_conn() as c:
        cur = c.execute(
            "DELETE FROM connected_accounts WHERE user_id = ? AND provider = ?",
            (user_id, provider),
        )
        c.commit()
        return cur.rowcount > 0


# === Hard-delete аккаунта (152-ФЗ ст.20 + GDPR Art.17) ===

def delete_user(user_id: str) -> dict:
    """Полностью удаляет пользователя и все связанные данные.
    Возвращает dict со счётчиками удалённого — для email-уведомления."""
    with get_conn() as c:
        # Сначала собираем статистику для отчёта пользователю
        stats = {
            "cloud_activities": c.execute(
                "SELECT COUNT(*) FROM cloud_activities WHERE user_id = ?",
                (user_id,)).fetchone()[0],
            "connected_accounts": c.execute(
                "SELECT COUNT(*) FROM connected_accounts WHERE user_id = ?",
                (user_id,)).fetchone()[0],
            "auth_tokens": c.execute(
                "SELECT COUNT(*) FROM auth_tokens WHERE user_id = ?",
                (user_id,)).fetchone()[0],
            "coach_for_athletes": c.execute(
                "SELECT COUNT(*) FROM users WHERE coach_user_id = ?",
                (user_id,)).fetchone()[0],
        }
        # Если этот user был coach — атлетам сбрасываем coach_user_id (они остаются)
        c.execute("UPDATE users SET coach_user_id = NULL WHERE coach_user_id = ?",
                  (user_id,))
        # Удаляем все связанные записи
        c.execute("DELETE FROM coach_invitations WHERE coach_user_id = ?", (user_id,))
        c.execute("DELETE FROM cloud_sync_runs WHERE user_id = ?", (user_id,))
        c.execute("DELETE FROM cloud_activities WHERE user_id = ?", (user_id,))
        c.execute("DELETE FROM connected_accounts WHERE user_id = ?", (user_id,))
        c.execute("DELETE FROM auth_tokens WHERE user_id = ?", (user_id,))
        c.execute("DELETE FROM users WHERE user_id = ?", (user_id,))
        c.commit()
    return stats
