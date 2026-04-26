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


def connect():
    """
    Возвращает подключение DB-API 2.0.
    При TURSO=on — libsql Connection с embedded replica.
    Иначе — стандартный sqlite3 Connection.
    """
    Path(DB_PATH).parent.mkdir(parents=True, exist_ok=True)
    if USE_TURSO:
        import libsql

        conn = libsql.connect(
            DB_PATH,
            sync_url=TURSO_URL,
            auth_token=TURSO_TOKEN,
        )
        # Подтянуть последнюю версию из облака сразу при коннекте
        try:
            conn.sync()
        except Exception as exc:
            # Сеть может быть недоступна — продолжаем на локальной копии
            print(f"[db] Warning: sync on connect failed: {exc}")
        return conn
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
