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

import hashlib
import hmac
import json
import os
import time
from typing import NamedTuple

import streamlit as st

try:
    import extra_streamlit_components as stx
    _HAS_COOKIES = True
except ImportError:
    _HAS_COOKIES = False

try:
    from itsdangerous import BadSignature, SignatureExpired, URLSafeTimedSerializer
    _HAS_ITSDANGEROUS = True
except ImportError:
    _HAS_ITSDANGEROUS = False

_COOKIE_NAME = "beatmetrics_auth"
_COOKIE_TTL_SECONDS = 30 * 24 * 3600  # 30 дней

# === SSO с signup_service (app.beatmetrics.ru) ===
# Cookie `bm_session` ставится signup_service на domain `.beatmetrics.ru`,
# подписан itsdangerous с BEATMETRICS_SESSION_SECRET. Мы расшифровываем тот же
# токен и автоматически логиним пользователя — без отдельной формы.
_BM_SESSION_COOKIE = "bm_session"
_BM_SESSION_TTL = 30 * 24 * 3600
_BM_SESSION_SECRET = os.getenv(
    "BEATMETRICS_SESSION_SECRET",
    "dev-secret-CHANGE-IN-PROD-please-use-32+chars",
)


def _read_bm_session() -> dict | None:
    """Возвращает payload {user_id, email, name} из bm_session cookie, или None.
    Использует st.context.cookies (server-side, доступен для HttpOnly cookies)."""
    if not _HAS_ITSDANGEROUS:
        return None
    try:
        raw = st.context.cookies.get(_BM_SESSION_COOKIE)
    except Exception:
        return None
    if not raw:
        return None
    try:
        ser = URLSafeTimedSerializer(_BM_SESSION_SECRET, salt="bm-session-v1")
        return ser.loads(str(raw), max_age=_BM_SESSION_TTL)
    except (BadSignature, SignatureExpired, Exception):
        return None


def _bm_session_to_authuser(payload: dict) -> "AuthUser | None":
    """signup_service-user → Streamlit AuthUser. Ищем mapping в users-table SQLite.
    Если у user заполнен athlete_id — используем его, иначе username = email."""
    if not payload:
        return None
    user_id = payload.get("user_id")
    email = (payload.get("email") or "").lower()
    name = payload.get("name") or email.split("@")[0]
    if not user_id or not email:
        return None
    # Подтянем athlete_id из users.athlete_id (если есть mapping)
    athlete_id = email
    role = "athlete"
    try:
        import sqlite3
        from pathlib import Path
        db_path = Path(__file__).resolve().parent / "data" / "garmin.db"
        with sqlite3.connect(str(db_path)) as conn:
            conn.row_factory = sqlite3.Row
            row = conn.execute(
                "SELECT athlete_id, role FROM users WHERE user_id = ?",
                (user_id,),
            ).fetchone()
            if row:
                athlete_id = row["athlete_id"] or email
                role = row["role"] or "athlete"
    except Exception:
        pass
    return AuthUser(
        username=email, name=name, role=role,
        athlete_id=athlete_id, is_local=False,
        visible_athletes=None,
    )


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


def _cookie_secret(users_cfg) -> str:
    """Секрет для HMAC-подписи cookie. Берём из [auth].cookie_secret или
    вычисляем стабильный fallback из хэшей паролей (меняется при смене пароля
    — старые куки автоматически инвалидируются, что нам и нужно)."""
    explicit = (users_cfg.get("cookie_secret") or "").strip()
    if explicit:
        return explicit
    parts = []
    for u in sorted(users_cfg.get("users", {}).keys()):
        parts.append(str(users_cfg["users"][u].get("password", "")))
    return hashlib.sha256("|".join(parts).encode()).hexdigest()


def _sign(value: str, secret: str) -> str:
    return hmac.new(secret.encode(), value.encode(), hashlib.sha256).hexdigest()


def _serialize_user(user: "AuthUser", secret: str) -> str:
    payload = {
        "u": user.username, "n": user.name, "r": user.role,
        "a": user.athlete_id,
        "v": list(user.visible_athletes) if user.visible_athletes else None,
        "exp": int(time.time()) + _COOKIE_TTL_SECONDS,
    }
    raw = json.dumps(payload, ensure_ascii=False, separators=(",", ":"))
    return raw + "::" + _sign(raw, secret)


def _deserialize_user(token: str, secret: str) -> "AuthUser | None":
    try:
        raw, sig = token.rsplit("::", 1)
        if not hmac.compare_digest(_sign(raw, secret), sig):
            return None
        data = json.loads(raw)
        if int(data.get("exp", 0)) < int(time.time()):
            return None
        visible = tuple(data["v"]) if data.get("v") else None
        return AuthUser(
            username=data["u"], name=data["n"], role=data["r"],
            athlete_id=data["a"], is_local=False, visible_athletes=visible,
        )
    except Exception:
        return None


def _get_cookie_manager():
    if not _HAS_COOKIES:
        return None
    # Кэшируем менеджер в session_state, чтобы не пересоздавать на каждом rerun
    if "_auth_cookie_mgr" not in st.session_state:
        st.session_state["_auth_cookie_mgr"] = stx.CookieManager(key="auth_cookie_manager")
    return st.session_state["_auth_cookie_mgr"]


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


_LOGIN_CSS = """
<style>
/* На login-форме скрываем сайдбар целиком — он показывает пункты меню
   незалогиненным пользователям, не нужно. */
[data-testid="stSidebar"], [data-testid="stSidebarCollapseButton"],
[data-testid="stSidebarCollapsedControl"], [data-testid="stLogo"] {
    display: none !important;
}
[data-testid="stAppViewContainer"] > section:first-child {
    display: none !important;
}
/* Фоновое фото лыжника поверх кремового фона дашборда (только на login).
   Перебиваем сразу все возможные Streamlit-контейнеры. */
html, body,
[data-testid="stApp"],
[data-testid="stAppViewContainer"],
[data-testid="stMain"],
.stApp {
    background-color: #F5F4EF !important;
    background-image:
        linear-gradient(rgba(245,244,239,0.20), rgba(245,244,239,0.50)),
        url('/app/static/auth-bg-skier.jpg') !important;
    background-size: cover !important;
    background-position: center center !important;
    background-attachment: fixed !important;
    background-repeat: no-repeat !important;
}
/* Прозрачный main-блок чтобы bg просвечивал через него */
[data-testid="stMain"] .block-container,
[data-testid="stMain"] section {
    background: transparent !important;
}
/* Карточка формы — frosted glass поверх фото лыжника */
[data-testid="stMain"] [data-testid="stForm"] {
    max-width: 380px;
    margin: 16px auto;
    padding: 28px 28px 24px;
    background: rgba(255,255,255,0.82) !important;
    backdrop-filter: blur(14px) saturate(150%);
    -webkit-backdrop-filter: blur(14px) saturate(150%);
    border: 1px solid rgba(255,255,255,0.55) !important;
    border-radius: 14px;
    box-shadow:
        0 8px 32px rgba(0,0,0,0.10),
        inset 0 1px 0 rgba(255,255,255,0.6) !important;
}
/* Видимая рамка — только на wrapper, input внутри прозрачный */
[data-testid="stMain"] [data-testid="stForm"] [data-testid="stTextInput"] [data-baseweb="input"],
[data-testid="stMain"] [data-testid="stForm"] [data-testid="stTextInput"] [data-baseweb="base-input"] {
    background: #fdfdfc !important;
    border: 1px solid #d8d6cd !important;
    border-radius: 6px !important;
    padding: 0 !important;
    height: 42px !important;
}
[data-testid="stMain"] [data-testid="stForm"] [data-testid="stTextInput"] [data-baseweb="input"] input,
[data-testid="stMain"] [data-testid="stForm"] [data-testid="stTextInput"] [data-baseweb="base-input"] input {
    background: transparent !important;
    border: none !important;
    box-shadow: none !important;
    padding: 0 12px !important;
    height: 100% !important;
    font-size: 14px !important;
    color: #1a1a18 !important;
}
[data-testid="stMain"] [data-testid="stForm"] [data-testid="stTextInput"] [data-baseweb="input"]:focus-within,
[data-testid="stMain"] [data-testid="stForm"] [data-testid="stTextInput"] [data-baseweb="base-input"]:focus-within {
    outline: 2px solid #3c3489 !important;
    outline-offset: -1px;
    border-color: transparent !important;
}
[data-testid="stMain"] [data-testid="stForm"] [data-testid="stTextInput"] label {
    font-size: 11px !important;
    color: #6b6a64 !important;
    text-transform: uppercase;
    letter-spacing: 0.5px;
    font-weight: 500;
    margin-bottom: 4px !important;
}
/* Submit-кнопка «Войти» — primary, фиолетовый */
[data-testid="stMain"] [data-testid="stForm"] [data-testid="stFormSubmitButton"] button {
    background: #3c3489 !important;
    color: #ffffff !important;
    border: 1px solid #3c3489 !important;
    border-radius: 6px !important;
    padding: 0 20px !important;
    font-weight: 500 !important;
    font-size: 14px !important;
    height: 42px !important;
    width: 100% !important;
    margin: 0 !important;
    transition: background .12s ease;
}
[data-testid="stMain"] [data-testid="stForm"] [data-testid="stFormSubmitButton"] button:hover {
    background: #2f2a73 !important;
    border-color: #2f2a73 !important;
}
/* «Регистрация» — ghost-кнопка справа от «Войти», через markdown-ссылку */
.bm-register-btn {
    display: flex; align-items: center; justify-content: center;
    height: 42px; width: 100%;
    background: #ffffff;
    color: #3c3489 !important;
    border: 1px solid #3c3489;
    border-radius: 6px;
    text-decoration: none !important;
    font-weight: 500; font-size: 14px;
    transition: background .12s ease;
}
.bm-register-btn:hover { background: #ebe9f7; }
.bm-login-logo { text-align: center; margin: 32px 0 4px; }
.bm-login-sub { text-align: center; color: #3c3489; font-size: 13px;
    margin-bottom: 4px; font-weight: 500; }
/* SSO redirect-screen для незалогиненных */
.bm-redirect-card {
    max-width: 380px; margin: 16px auto; padding: 28px;
    background: rgba(255,255,255,0.82);
    backdrop-filter: blur(14px) saturate(150%);
    -webkit-backdrop-filter: blur(14px) saturate(150%);
    border: 1px solid rgba(255,255,255,0.55);
    border-radius: 14px;
    box-shadow: 0 8px 32px rgba(0,0,0,0.10),
                inset 0 1px 0 rgba(255,255,255,0.6);
}
.bm-redirect-msg {
    text-align: center; color: #1a1a18; font-size: 14px;
    line-height: 1.5; margin-bottom: 18px;
}
.bm-redirect-msg b { color: #3c3489; }
.bm-redirect-cta {
    display: flex; align-items: center; justify-content: center;
    height: 42px; width: 100%;
    background: #3c3489 !important;
    color: #ffffff !important;
    border: 1px solid #3c3489;
    border-radius: 6px;
    text-decoration: none !important;
    font-weight: 500; font-size: 14px;
    transition: background .12s ease;
}
.bm-redirect-cta:hover { background: #2f2a73 !important; }
.bm-redirect-coach-hint {
    margin-top: 16px; text-align: center;
    font-size: 11px; color: #6b6a64;
}
.bm-redirect-coach-hint a {
    color: #3c3489 !important; font-weight: 500;
    text-decoration: none !important;
}
.bm-redirect-coach-hint a:hover { text-decoration: underline !important; }
</style>
"""

_LOGIN_LOGO_SVG = """
<div class="bm-login-logo">
<svg viewBox="0 0 320 64" width="220" height="44" aria-label="BeatMetrics">
  <rect x="0" y="0" width="64" height="64" rx="14" fill="#3c3489"/>
  <path d="M 14 12 L 14 52" fill="none" stroke="#fff" stroke-width="4" stroke-linecap="round"/>
  <path d="M 14 30 Q 14 20 26 20 Q 38 20 38 36 Q 38 52 26 52 Q 14 52 14 42" fill="none" stroke="#fff" stroke-width="4" stroke-linecap="round" stroke-linejoin="round"/>
  <path d="M 44 36 L 46 36 L 48 31 L 51 41 L 53 36 L 55 36" fill="none" stroke="#fff" stroke-width="2.6" stroke-linecap="round" stroke-linejoin="round"/>
  <text x="80" y="42" font-family="-apple-system, 'Segoe UI', system-ui, sans-serif" font-size="32" font-weight="500" fill="#1a1a18" letter-spacing="-0.02em">BeatMetrics</text>
</svg>
</div>
<div class="bm-login-sub">тренируйся осознанно</div>
"""


def _login_form(users_cfg) -> AuthUser:
    # 1) Уже в session_state — возвращаем сразу
    if "auth_user" in st.session_state:
        return st.session_state["auth_user"]

    secret = _cookie_secret(users_cfg)
    cm = _get_cookie_manager()

    # 2) SSO: cookie `bm_session` от signup_service на .beatmetrics.ru
    #    Если пользователь залогинен на app.beatmetrics.ru — пускаем сюда без формы.
    bm_payload = _read_bm_session()
    if bm_payload:
        bm_user = _bm_session_to_authuser(bm_payload)
        if bm_user is not None:
            st.session_state["auth_user"] = bm_user
            return bm_user

    # 3) Старая система: cookie от Streamlit-формы (для админ-логина coach)
    if cm is not None:
        token = cm.get(_COOKIE_NAME)
        if token:
            restored = _deserialize_user(str(token), secret)
            if restored is not None:
                st.session_state["auth_user"] = restored
                return restored

    # 4) SSO-first: для незалогиненных рисуем не форму, а redirect-screen
    #    на единую точку входа app.beatmetrics.ru/login. Старая форма остаётся
    #    только за ?coach_login=1 (технический fallback для coach в обход SSO,
    #    например когда SSO-секрет рассинхронизирован).
    is_coach_fallback = "coach_login" in st.query_params

    st.markdown(_LOGIN_CSS, unsafe_allow_html=True)
    st.markdown(_LOGIN_LOGO_SVG, unsafe_allow_html=True)

    if not is_coach_fallback:
        st.markdown(
            '<div class="bm-redirect-card">'
            '<div class="bm-redirect-msg">'
            'Войдите через <b>основной кабинет</b> BeatMetrics — '
            'там единая регистрация и Google-логин.'
            '</div>'
            '<a class="bm-redirect-cta" target="_self" '
            'href="https://app.beatmetrics.ru/login?next='
            'https%3A%2F%2Fbeatmetrics.ru%2Fdashboard%2F">Перейти ко входу →</a>'
            '<div class="bm-redirect-coach-hint">'
            'Тренеру нужен прямой вход? '
            '<a href="?coach_login=1">Войти через старую форму</a>'
            '</div>'
            '</div>',
            unsafe_allow_html=True,
        )
        st.stop()

    # Coach-fallback: старая Streamlit-форма (доступна за ?coach_login=1)
    with st.form("login_form", clear_on_submit=False):
        username = st.text_input("Логин", autocomplete="username")
        password = st.text_input(
            "Пароль", type="password", autocomplete="current-password",
        )
        _col_l, _col_r = st.columns(2)
        with _col_l:
            submitted = st.form_submit_button("Войти", use_container_width=True)
        with _col_r:
            # «Регистрация» — ссылка-кнопка на отдельный signup-сервис
            st.markdown(
                '<a href="https://app.beatmetrics.ru/signup" target="_self" '
                'class="bm-register-btn">Регистрация&nbsp;↗</a>',
                unsafe_allow_html=True,
            )

    if submitted:
        users = users_cfg["users"]
        record = users.get(username.strip())
        if record and _check_password(password, record.get("password", "")):
            visible_raw = record.get("visible_athletes")
            visible = (tuple(str(a).strip() for a in visible_raw if str(a).strip())
                       if visible_raw else None)
            user = AuthUser(
                username=username.strip(),
                name=record.get("name", username.strip()),
                role=record.get("role", "athlete"),
                athlete_id=record.get("athlete_id", username.strip()),
                is_local=False,
                visible_athletes=visible,
            )
            st.session_state["auth_user"] = user
            # Сохраняем подписанный токен в cookie (30 дней)
            if cm is not None:
                token = _serialize_user(user, secret)
                cm.set(_COOKIE_NAME, token, max_age=_COOKIE_TTL_SECONDS)
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
        cm = _get_cookie_manager()
        if cm is not None:
            try:
                cm.delete(_COOKIE_NAME)
            except Exception:
                pass
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
