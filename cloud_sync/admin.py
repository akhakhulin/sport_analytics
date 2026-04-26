"""
Админ-CLI для облачных атлетов.

Использование (из корня проекта):

    # 1. Один раз — сгенерить мастер-ключ:
    python -m cloud_sync.admin init-key

    # 2. Добавить атлета (живой логин, спросит 2FA):
    python -m cloud_sync.admin add maria_iva --name "Мария Иванова"

    # 3. Список:
    python -m cloud_sync.admin list

    # 4. Деактивировать (синк прекратится, запись остаётся):
    python -m cloud_sync.admin disable maria_iva

    # 5. Удалить полностью:
    python -m cloud_sync.admin remove maria_iva

    # 6. Перелогинить (через ~год, когда токены протухли):
    python -m cloud_sync.admin renew maria_iva

    # 7. Запустить синк прямо сейчас (для проверки или экстренной выгрузки):
    python -m cloud_sync.admin run [<athlete_id>]
"""

from __future__ import annotations

import argparse
import getpass
import sys
from datetime import datetime

from dotenv import load_dotenv
load_dotenv()

import db as dbm
from cloud_sync import crypto
from cloud_sync.db_schema import migrate
from garminconnect import Garmin, GarminConnectAuthenticationError
import garmin_sync


def _conn():
    conn = dbm.connect()
    migrate(conn)
    return conn


def cmd_init_key(_args) -> int:
    key = crypto.generate_master_key()
    print()
    print("Сгенерирован новый CLOUD_MASTER_KEY.")
    print("Сохрани его в двух местах:")
    print("  - локально: .env  ->  CLOUD_MASTER_KEY=" + key)
    print("  - GitHub Actions Secrets  ->  CLOUD_MASTER_KEY")
    print()
    print("ВНИМАНИЕ: ключ показывается ОДИН раз. Без него все записи в")
    print("cloud_athletes расшифровать невозможно. Потеряешь — нужно будет")
    print("заново логинить всех облачных атлетов.")
    return 0


def _interactive_login(email: str, password: str) -> str:
    """
    Живой логин в Garmin (с 2FA, который читается с stdin).
    Возвращает строку токенов для шифрования.
    """
    def _ask_mfa() -> str:
        return input("Garmin 2FA код (если пришёл в SMS/email): ").strip()

    client = Garmin(email, password, prompt_mfa=_ask_mfa)
    client.login(tokenstore=None)
    return client.client.dumps()


def cmd_add(args) -> int:
    athlete_id = args.athlete_id.strip()
    name = (args.name or athlete_id).strip()

    print(f"\nДобавляю облачного атлета: {athlete_id} ({name})")
    print("Garmin-креды НЕ сохраняются на диск, шифруются и кладутся в Turso.\n")

    email = input("Garmin email: ").strip()
    password = getpass.getpass("Garmin password: ")

    print("\nЛогинюсь в Garmin (если включён 2FA — потребуется код)...")
    try:
        tokens_str = _interactive_login(email, password)
    except Exception as exc:  # noqa: BLE001
        print(f"\n[ОШИБКА] Логин не удался: {exc}", file=sys.stderr)
        return 1

    pwd_enc = crypto.encrypt(password)
    tok_enc = crypto.encrypt(tokens_str)

    conn = _conn()
    conn.execute(
        """
        INSERT INTO cloud_athletes
            (athlete_id, name, garmin_email, password_enc, tokens_enc, active, created_at)
        VALUES (?, ?, ?, ?, ?, 1, ?)
        ON CONFLICT(athlete_id) DO UPDATE SET
            name=excluded.name,
            garmin_email=excluded.garmin_email,
            password_enc=excluded.password_enc,
            tokens_enc=excluded.tokens_enc,
            active=1,
            last_error=NULL
        """,
        (athlete_id, name, email, pwd_enc, tok_enc,
         datetime.utcnow().isoformat()),
    )
    conn.commit()
    dbm.sync(conn)
    conn.close()

    print(f"\n[OK] {athlete_id} добавлен. Запусти `python -m cloud_sync.admin run "
          f"{athlete_id}` для первой выгрузки.")
    return 0


def cmd_renew(args) -> int:
    athlete_id = args.athlete_id.strip()
    conn = _conn()
    row = conn.execute(
        "SELECT garmin_email, password_enc FROM cloud_athletes WHERE athlete_id=?",
        (athlete_id,),
    ).fetchone()
    if row is None:
        print(f"Не найден: {athlete_id}", file=sys.stderr)
        return 1
    email, pwd_enc = row
    password = crypto.decrypt(pwd_enc)

    print(f"\nПерелогин для {athlete_id} ({email}). 2FA-код потребуется снова.")
    try:
        tokens_str = _interactive_login(email, password)
    except Exception as exc:  # noqa: BLE001
        print(f"[ОШИБКА] {exc}", file=sys.stderr)
        return 1

    conn.execute(
        "UPDATE cloud_athletes SET tokens_enc=?, last_error=NULL WHERE athlete_id=?",
        (crypto.encrypt(tokens_str), athlete_id),
    )
    conn.commit()
    dbm.sync(conn)
    conn.close()
    print(f"[OK] {athlete_id} — токены обновлены.")
    return 0


def cmd_list(_args) -> int:
    conn = _conn()
    rows = conn.execute(
        """
        SELECT athlete_id, name, garmin_email, active, last_sync, last_error
        FROM cloud_athletes
        ORDER BY athlete_id
        """
    ).fetchall()
    conn.close()
    if not rows:
        print("Облачных атлетов нет. Добавь: `python -m cloud_sync.admin add <id>`")
        return 0
    print(f"{'athlete_id':<20} {'name':<20} {'email':<28} {'active':<7} {'last_sync':<20}")
    print("-" * 100)
    for athlete_id, name, email, active, last_sync, last_err in rows:
        line = (
            f"{athlete_id:<20} {(name or ''):<20} {email:<28} "
            f"{'yes' if active else 'no':<7} {(last_sync or '—'):<20}"
        )
        if last_err:
            line += f"  ⚠ {last_err}"
        print(line)
    return 0


def cmd_disable(args) -> int:
    conn = _conn()
    conn.execute(
        "UPDATE cloud_athletes SET active=0 WHERE athlete_id=?",
        (args.athlete_id,),
    )
    conn.commit()
    dbm.sync(conn)
    conn.close()
    print(f"[OK] {args.athlete_id} деактивирован (синк прекращён, данные сохранены).")
    return 0


def cmd_remove(args) -> int:
    conn = _conn()
    conn.execute("DELETE FROM cloud_athletes WHERE athlete_id=?", (args.athlete_id,))
    conn.commit()
    dbm.sync(conn)
    conn.close()
    print(f"[OK] {args.athlete_id} удалён из cloud_athletes "
          "(тренировочные данные в activities/daily/sleep/hrv остались).")
    return 0


def cmd_run(args) -> int:
    from cloud_sync.sync_all import run_all, run_one
    if args.athlete_id:
        return run_one(args.athlete_id)
    return run_all()


def main() -> int:
    p = argparse.ArgumentParser(prog="cloud_sync.admin")
    sub = p.add_subparsers(dest="cmd", required=True)

    sub.add_parser("init-key", help="Сгенерировать мастер-ключ").set_defaults(
        func=cmd_init_key)

    p_add = sub.add_parser("add", help="Добавить облачного атлета")
    p_add.add_argument("athlete_id")
    p_add.add_argument("--name", default=None)
    p_add.set_defaults(func=cmd_add)

    p_renew = sub.add_parser("renew", help="Перелогин (после года)")
    p_renew.add_argument("athlete_id")
    p_renew.set_defaults(func=cmd_renew)

    sub.add_parser("list", help="Показать всех облачных атлетов").set_defaults(
        func=cmd_list)

    p_dis = sub.add_parser("disable", help="Выключить синк (запись остаётся)")
    p_dis.add_argument("athlete_id")
    p_dis.set_defaults(func=cmd_disable)

    p_rm = sub.add_parser("remove", help="Удалить из cloud_athletes")
    p_rm.add_argument("athlete_id")
    p_rm.set_defaults(func=cmd_remove)

    p_run = sub.add_parser("run", help="Прогнать синк сейчас")
    p_run.add_argument("athlete_id", nargs="?", default=None)
    p_run.set_defaults(func=cmd_run)

    args = p.parse_args()
    return args.func(args) or 0


if __name__ == "__main__":
    raise SystemExit(main())
