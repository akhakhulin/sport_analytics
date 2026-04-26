"""
Аутентификация для дашборда.

Если в st.secrets есть секция [auth] — показывает форму логина и не пускает
дальше без правильной пары логин/пароль. Пароли хранятся как bcrypt-хэши.

Если секции нет — fallback на ENV (ATHLETE_ID + IS_ADMIN). Локальный режим
запуска (`dashboard.cmd`) работает как раньше, без формы логина.

Хранение учёток (Streamlit Cloud → Settings → Secrets):

    [auth]
    cookie_name = "garmin_dashboard_auth"

    [auth.users.coach]
    name = "Алексей (тренер)"
    password = "$2b$12$..."     # bcrypt
    role = "coach"               # coach — видит всех; athlete — только себя
    athlete_id = "coach"

    [auth.users.ivan]
    name = "Иван Петров"
    password = "$2b$12$..."
    role = "athlete"
    athlete_id = "ivan_petrov"

Хэш пароля: `python make_password.py`.
"""

from __future__ import annotations

import os
from typing import NamedTuple

import streamlit as st


class AuthUser(NamedTuple):
    username: str
    name: str
    role: str          # "coach" | "athlete"
    athlete_id: str
    is_local: bool     # True — ENV-fallback (без формы)
    visible_athletes: tuple[str, ...] | None  # None = видит всех (для coach без ограничения)


def _users_cfg():
    try:
        auth = st.secrets["auth"]
    except (KeyError, FileNotFoundError, st.errors.StreamlitSecretNotFoundError):
        return None
    except Exception:
        return None
    if "users" not in auth:
        return None
    return auth


def _check_password(plain: str, stored: str) -> bool:
    if not stored:
        return False
    if stored.startswith("$2"):
        import bcrypt
        try:
            return bcrypt.checkpw(plain.encode("utf-8"), stored.encode("utf-8"))
        except ValueError:
            return False
    # plaintext поддерживается только если хэш не задан — для локальной отладки
    return plain == stored


def _login_form(users_cfg) -> AuthUser:
    if "auth_user" in st.session_state:
        return st.session_state["auth_user"]

    st.markdown("## Sportsmen Analytics")

    with st.form("login_form", clear_on_submit=False):
        username = st.text_input("Логин", autocomplete="username")
        password = st.text_input("Пароль", type="password",
                                 autocomplete="current-password")
        submitted = st.form_submit_button("Войти")

    if submitted:
        users = users_cfg["users"]
        record = users.get(username.strip())
        if record and _check_password(password, record.get("password", "")):
            visible_raw = record.get("visible_athletes")
            if visible_raw:
                visible = tuple(str(a).strip() for a in visible_raw if str(a).strip())
            else:
                visible = None
            user = AuthUser(
                username=username.strip(),
                name=record.get("name", username.strip()),
                role=record.get("role", "athlete"),
                athlete_id=record.get("athlete_id", username.strip()),
                is_local=False,
                visible_athletes=visible,
            )
            st.session_state["auth_user"] = user
            st.rerun()
        else:
            st.error("Неверный логин или пароль.")

    st.stop()


def require_login() -> AuthUser:
    cfg = _users_cfg()
    if cfg is None:
        athlete_id = (os.getenv("ATHLETE_ID") or "me").strip()
        is_admin = (os.getenv("IS_ADMIN") or "false").strip().lower() in (
            "true", "1", "yes",
        )
        return AuthUser(
            username=athlete_id,
            name=athlete_id,
            role="coach" if is_admin else "athlete",
            athlete_id=athlete_id,
            is_local=True,
            visible_athletes=None,
        )
    return _login_form(cfg)


def logout_button(label: str = "Выйти") -> None:
    user = st.session_state.get("auth_user")
    if user is None or user.is_local:
        return
    if st.sidebar.button(label, use_container_width=True, key="auth_logout"):
        st.session_state.pop("auth_user", None)
        st.rerun()


def apply_secrets_to_env() -> None:
    """
    Переносит [turso] из st.secrets в переменные окружения ДО импорта db.

    Должно вызваться до `import db`, чтобы db.py (читает env при импорте)
    подхватил облачные креды при деплое на Streamlit Cloud. Локальный
    `.env` через load_dotenv() продолжает работать как раньше.
    """
    try:
        has_turso = "turso" in st.secrets
    except Exception:
        return
    if not has_turso:
        return
    turso = st.secrets["turso"]
    if "url" in turso:
        os.environ["TURSO_DATABASE_URL"] = str(turso["url"]).strip()
    if "token" in turso:
        os.environ["TURSO_AUTH_TOKEN"] = str(turso["token"]).strip()
