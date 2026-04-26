"""
Генерирует bcrypt-хэш пароля для secrets.toml.

Способы запуска:

    # Интерактивно (скрытый ввод — работает в PowerShell/cmd):
    python make_password.py

    # Через аргумент (работает везде, но пароль виден в команде):
    python make_password.py "gold-bear-99"

Выводит строку вида `password = "$2b$12$..."` — её нужно вставить в
секцию [auth.users.<логин>] в Streamlit Cloud Secrets.
"""

from __future__ import annotations

import sys

import bcrypt


def _interactive_input() -> bytes | None:
    try:
        import getpass
        pwd = getpass.getpass("Пароль (ввод скрыт): ")
        if not pwd:
            return None
        confirm = getpass.getpass("Повторите: ")
        if pwd != confirm:
            print("Пароли не совпадают.", file=sys.stderr)
            return None
        return pwd.encode("utf-8")
    except Exception as exc:  # noqa: BLE001
        print(f"[!] Скрытый ввод не сработал ({exc}).", file=sys.stderr)
        print("    Запустите с аргументом: python make_password.py \"ваш_пароль\"",
              file=sys.stderr)
        return None


def main() -> int:
    if len(sys.argv) >= 2:
        # Пароль через argv — для Git Bash и других терминалов, где
        # скрытый ввод не работает. ВНИМАНИЕ: попадает в историю shell!
        pwd_str = sys.argv[1]
        if len(pwd_str) < 6:
            print("Минимум 6 символов.", file=sys.stderr)
            return 1
        pwd = pwd_str.encode("utf-8")
    else:
        result = _interactive_input()
        if result is None:
            return 1
        if len(result) < 6:
            print("Минимум 6 символов.", file=sys.stderr)
            return 1
        pwd = result

    hashed = bcrypt.hashpw(pwd, bcrypt.gensalt()).decode("utf-8")
    print()
    print("Скопируйте в Streamlit Secrets под нужного пользователя:")
    print(f'    password = "{hashed}"')
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
