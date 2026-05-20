"""Прямой disable/enable атлета в Turso, минуя migrate.

Использование:
    python tools/disable_athlete_turso.py <athlete_id> [--enable]

По умолчанию деактивирует. С --enable — возвращает active=1.

Это быстрее чем admin.disable/enable потому что:
- Не делает первоначального sync 56 МБ
- Не проходит migrate (CREATE TABLE / ALTER TABLE)
- Прямой HTTP к Turso, не libsql replica
"""
from __future__ import annotations

import os
import sys
from pathlib import Path

from dotenv import load_dotenv

load_dotenv()

import libsql


def main() -> int:
    args = [a for a in sys.argv[1:] if not a.startswith("--")]
    flags = [a for a in sys.argv[1:] if a.startswith("--")]

    if len(args) != 1:
        print(f"Usage: {sys.argv[0]} <athlete_id> [--enable]")
        return 1

    athlete_id = args[0]
    target_active = 1 if "--enable" in flags else 0
    action = "enable" if target_active else "disable"

    url = os.getenv("TURSO_DATABASE_URL", "").strip()
    token = os.getenv("TURSO_AUTH_TOKEN", "").strip()

    if not url or not token:
        print("TURSO_DATABASE_URL и TURSO_AUTH_TOKEN не найдены в .env")
        return 1

    # Преобразуем libsql:// в https:// для прямого подключения
    if url.startswith("libsql://"):
        http_url = "https://" + url[len("libsql://"):]
    else:
        http_url = url

    print(f"Подключаюсь к {http_url}...")
    conn = libsql.connect(database=http_url, auth_token=token)
    print("Подключено")

    # Проверяем текущий статус
    cur = conn.execute(
        "SELECT athlete_id, active FROM cloud_athletes WHERE athlete_id=?",
        (athlete_id,),
    )
    row = cur.fetchone()
    if not row:
        print(f"Атлет {athlete_id} не найден")
        return 1
    print(f"До: {row[0]} active={row[1]}")

    if row[1] == target_active:
        print(f"Уже active={target_active}, ничего менять не нужно")
        return 0

    # Set active state
    conn.execute(
        "UPDATE cloud_athletes SET active=? WHERE athlete_id=?",
        (target_active, athlete_id),
    )
    conn.commit()
    print(f"UPDATE active={target_active} ({action}) выполнен и закоммичен")

    # Проверка
    cur = conn.execute(
        "SELECT athlete_id, active FROM cloud_athletes WHERE athlete_id=?",
        (athlete_id,),
    )
    row = cur.fetchone()
    print(f"После: {row[0]} active={row[1]}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
