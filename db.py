"""
Единая точка подключения к БД.

Если в .env заданы TURSO_DATABASE_URL и TURSO_AUTH_TOKEN — используется
embedded replica libsql: локальный файл синхронизируется с облаком Turso.
Иначе — обычный sqlite3, файл по DB_PATH.

Embedded replica = локальный SQLite-файл, который libsql сам держит в синке
с удалённой БД. Чтения быстрые (с диска), записи отправляются в Turso
и реплицируются обратно. После любых изменений нужно вызывать sync().
"""

from __future__ import annotations

import os
import sqlite3
from pathlib import Path

from dotenv import load_dotenv

load_dotenv()

DB_PATH = os.getenv("DB_PATH", "./data/garmin.db")
TURSO_URL = os.getenv("TURSO_DATABASE_URL", "").strip()
TURSO_TOKEN = os.getenv("TURSO_AUTH_TOKEN", "").strip()

USE_TURSO = bool(TURSO_URL and TURSO_TOKEN)


def _purge_replica_cache(reason: str) -> None:
    """Удаляет локальный кэш replica + сайдкары. Безопасно — Turso source of truth."""
    print(f"[db] Очистка локального replica-кэша: {reason}")
    base = Path(DB_PATH)
    candidates = [
        base,
        base.with_suffix(base.suffix + "-info"),
        base.with_suffix(base.suffix + "-shm"),
        base.with_suffix(base.suffix + "-wal"),
        base.with_suffix(base.suffix + ".meta"),
        Path(str(base) + "-info"),
        Path(str(base) + "-shm"),
        Path(str(base) + "-wal"),
        Path(str(base) + "-client_wal_index"),
    ]
    for p in candidates:
        try:
            if p.exists():
                p.unlink()
        except Exception as exc:  # noqa: BLE001
            print(f"[db]   не получилось удалить {p}: {exc}")


def _open_libsql():
    import libsql
    conn = libsql.connect(
        DB_PATH,
        sync_url=TURSO_URL,
        auth_token=TURSO_TOKEN,
    )
    conn.sync()
    return conn


def connect():
    """
    Возвращает подключение DB-API 2.0.
    При TURSO=on — libsql Connection с embedded replica.
    Иначе — стандартный sqlite3 Connection.
    """
    Path(DB_PATH).parent.mkdir(parents=True, exist_ok=True)
    if USE_TURSO:
        try:
            return _open_libsql()
        except Exception as exc:
            err = str(exc).lower()
            # На Streamlit Cloud между рестартами файл replica может остаться
            # без метаданных — libsql отказывается синкаться.
            # Чистим кэш и пробуем снова — Turso всё равно source of truth.
            if ("metadata" in err or "invalid local state" in err
                    or "checksum" in err):
                _purge_replica_cache(reason=str(exc)[:120])
                return _open_libsql()
            # Сеть недоступна — отдаём connection на пустую локальную replica,
            # чтобы хотя бы не падать совсем (читать будет нечего)
            print(f"[db] Warning: sync on connect failed: {exc}")
            import libsql
            return libsql.connect(
                DB_PATH, sync_url=TURSO_URL, auth_token=TURSO_TOKEN,
            )
    return sqlite3.connect(DB_PATH)


def sync(conn) -> None:
    """Принудительный пуш локальных изменений в Turso. На sqlite3 — no-op."""
    if USE_TURSO and hasattr(conn, "sync"):
        try:
            conn.sync()
        except Exception as exc:
            print(f"[db] Warning: sync failed: {exc}")


def is_turso() -> bool:
    return USE_TURSO


def info() -> str:
    if USE_TURSO:
        return f"Turso (replica: {DB_PATH}, remote: {TURSO_URL})"
    return f"local SQLite ({DB_PATH})"
