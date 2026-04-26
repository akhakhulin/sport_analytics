"""
Генерирует bcrypt-хэш пароля для secrets.toml.

Запуск: python make_password.py
Выводит строку вида `password = "$2b$12$..."` — её нужно вставить
в секцию [auth.users.<логин>] в Streamlit Cloud Secrets или
в локальный .streamlit/secrets.toml.
"""

from __future__ import annotations

import getpass
import sys

import bcrypt


def main() -> int:
    pwd = getpass.getpass("Пароль: ").encode("utf-8")
    confirm = getpass.getpass("Повторите: ").encode("utf-8")
    if pwd != confirm:
        print("Пароли не совпадают.", file=sys.stderr)
        return 1
    if len(pwd) < 6:
        print("Минимум 6 символов.", file=sys.stderr)
        return 1
    hashed = bcrypt.hashpw(pwd, bcrypt.gensalt()).decode("utf-8")
    print()
    print("Скопируйте в secrets.toml под нужного пользователя:")
    print(f'    password = "{hashed}"')
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
