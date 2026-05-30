"""
Разовый интерактивный перелогин в Garmin с вводом 2FA через файл.

Запускается как фоновый процесс. Доходит до запроса MFA-кода (Garmin
к этому моменту уже отправил код на почту/SMS/в приложение), затем
ждёт, пока код появится в logs/mfa_code.txt, дозавершает вход и
сохраняет токены в GARMIN_TOKENS_DIR. После этого автосинк оживёт.

Статус пишется в logs/mfa_status.txt:
  STARTED -> LOGGING_IN -> WAITING_FOR_CODE -> GOT_CODE -> SUCCESS
  или ERROR: <текст>
"""
from __future__ import annotations

import os
import sys
import time
import traceback
from pathlib import Path

BASE = Path(r"C:\Claude_Projects\garmin_analytics")
os.chdir(BASE)

from dotenv import load_dotenv  # noqa: E402

load_dotenv(BASE / ".env")

from garminconnect import Garmin  # noqa: E402

LOGS = BASE / "logs"
LOGS.mkdir(exist_ok=True)
CODE_FILE = LOGS / "mfa_code.txt"
STATUS_FILE = LOGS / "mfa_status.txt"


def status(s: str) -> None:
    STATUS_FILE.write_text(s, encoding="utf-8")
    print(s, flush=True)


def wait_for_code() -> str:
    """Вызывается, когда Garmin требует MFA. Код уже отправлен атлету."""
    status("WAITING_FOR_CODE")
    deadline = time.time() + 900  # 15 минут на ввод
    while time.time() < deadline:
        if CODE_FILE.exists():
            code = CODE_FILE.read_text(encoding="utf-8").strip()
            if code:
                try:
                    CODE_FILE.unlink()
                except OSError:
                    pass
                status("GOT_CODE")
                return code
        time.sleep(2)
    raise TimeoutError("MFA-код не пришёл за 15 минут")


def main() -> int:
    email = os.getenv("GARMIN_EMAIL") or ""
    password = os.getenv("GARMIN_PASSWORD") or ""
    # Синк (scripts\sync_garmin.bat) держит токены в ./garminconnect (БЕЗ точки),
    # переопределяя .env. Пишем туда же, иначе синк новые токены не подхватит.
    tokens_dir = "./garminconnect"
    tokens_dir = str((BASE / tokens_dir).resolve())
    Path(tokens_dir).mkdir(parents=True, exist_ok=True)

    if CODE_FILE.exists():
        try:
            CODE_FILE.unlink()
        except OSError:
            pass

    if not email or not password:
        status("ERROR: нет GARMIN_EMAIL/PASSWORD в .env")
        return 2

    status("STARTED")
    client = Garmin(email, password, prompt_mfa=wait_for_code)
    status("LOGGING_IN")
    client.login(tokenstore=tokens_dir)
    # login уже дампит токены, но подстрахуемся
    try:
        client.client.dump(tokens_dir)
    except Exception:
        pass
    # Проверка, что вход реально рабочий
    name = getattr(client, "display_name", None) or getattr(client, "full_name", "")
    status(f"SUCCESS: вход ок ({name or 'profile loaded'})")
    return 0


if __name__ == "__main__":
    try:
        sys.exit(main())
    except Exception as e:  # noqa: BLE001
        STATUS_FILE.write_text(f"ERROR: {e}", encoding="utf-8")
        print("ERROR:", e, file=sys.stderr)
        traceback.print_exc()
        sys.exit(1)
