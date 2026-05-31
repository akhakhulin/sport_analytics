"""FastAPI signup-сервис: /, /signup, /login, /done, /logout.

Сессия — подписанная HttpOnly cookie `bm_session`, TTL 30 дней,
HMAC через itsdangerous. В проде поднимется HTTPS-only.
"""
from __future__ import annotations

import os
from pathlib import Path

from fastapi import FastAPI, Form, Request, Response
from fastapi.responses import HTMLResponse, RedirectResponse
from fastapi.staticfiles import StaticFiles
from fastapi.templating import Jinja2Templates

from datetime import datetime, timezone

from starlette.middleware.sessions import SessionMiddleware

from . import auth_google
from . import db as users_db
from . import email_sender
from . import oauth as oauth_module
from ._session import (
    SESSION_COOKIE,
    SESSION_SECRET,
    clear_session as _clear_session,
    get_current_user as _get_current_user,
    set_session as _set_session,
)


# === SVG-иконки провайдеров (для onboarding_connect) ===
_ICON_POLAR = (
    '<svg width="22" height="22" viewBox="0 0 24 24" fill="none" aria-hidden="true">'
    '<circle cx="12" cy="12" r="9" stroke="#A32D2D" stroke-width="1.6"/>'
    '<path d="M12 6v6l4 2" stroke="#A32D2D" stroke-width="1.6" stroke-linecap="round"/>'
    "</svg>"
)
_ICON_SUUNTO = (
    '<svg width="22" height="22" viewBox="0 0 24 24" fill="none" aria-hidden="true">'
    '<rect x="4" y="4" width="16" height="16" rx="3" stroke="#1a1a18" stroke-width="1.6"/>'
    '<circle cx="12" cy="12" r="3" stroke="#1a1a18" stroke-width="1.6"/>'
    "</svg>"
)
_ICON_COROS = (
    '<svg width="22" height="22" viewBox="0 0 24 24" aria-hidden="true">'
    '<circle cx="12" cy="12" r="11" fill="#1a1a18"/>'
    '<text x="12" y="16" font-family="system-ui,sans-serif" font-size="11" '
    'font-weight="700" fill="#fff" text-anchor="middle">C</text>'
    "</svg>"
)
_ICON_APPLE = (
    '<svg width="20" height="22" viewBox="0 0 24 24" fill="#1a1a18" aria-hidden="true">'
    '<path d="M17.05 20.28c-.98.95-2.05.94-3.08.49-1.09-.46-2.09-.48-3.24 0-'
    "1.44.62-2.2.44-3.06-.49C2.79 15.25 3.51 7.59 9.05 7.31c1.35.07 2.29.74 "
    "3.08.8 1.18-.24 2.31-.93 3.57-.84 1.51.12 2.65.72 3.4 1.8-3.12 1.87-2.38 "
    "5.98.48 7.13-.57 1.5-1.31 2.99-2.54 4.09zM12.03 7.25c-.15-2.23 1.66-4.07 "
    '3.74-4.25.29 2.58-2.34 4.5-3.74 4.25z"/>'
    "</svg>"
)

BASE = Path(__file__).resolve().parent
templates = Jinja2Templates(directory=str(BASE / "templates"))

app = FastAPI(title="BeatMetrics signup", docs_url=None, redoc_url=None)
# SessionMiddleware нужен authlib для хранения OAuth state/PKCE.
# Используем тот же SESSION_SECRET что и для itsdangerous-сессии.
app.add_middleware(
    SessionMiddleware,
    secret_key=SESSION_SECRET,
    session_cookie="bm_auth_session",  # отдельная cookie от bm_session
    max_age=600,
    same_site="lax",
    https_only=False,
)
app.mount("/static", StaticFiles(directory=str(BASE / "static")), name="static")
app.include_router(oauth_module.router)
app.include_router(auth_google.router)


@app.on_event("startup")
async def _startup() -> None:
    users_db.init_schema()


def _ctx(request: Request, **extra) -> dict:
    """Базовый context — request передаём в TemplateResponse отдельно
    (новый Starlette API), сюда кладём только данные шаблона."""
    base = {
        "user": _get_current_user(request),
        "google_enabled": auth_google.is_configured(),
    }
    base.update(extra)
    return base


# === Routes ===


@app.get("/", response_class=HTMLResponse)
async def landing(request: Request):
    user = _get_current_user(request)
    if user:
        return RedirectResponse("/done", status_code=303)
    return RedirectResponse("/signup", status_code=303)


def _resolve_invitation(invite_token: str | None):
    """Возвращает (invitation_row, error) — error если токен есть но невалидный."""
    if not invite_token:
        return None, None
    inv = users_db.find_invitation(invite_token.strip())
    if inv is None:
        return None, "Приглашение не найдено или ссылка устарела"
    if inv["used_by_user_id"]:
        return None, "Это приглашение уже использовано"
    return inv, None


@app.get("/signup", response_class=HTMLResponse)
async def signup_get(request: Request, invite: str | None = None):
    current_user = _get_current_user(request)
    # НЕ делаем silent-redirect — рендерим форму с баннером "уже вошёл как X",
    # чтобы было очевидно как выйти и зарегаться заново.
    invitation, inv_error = _resolve_invitation(invite)
    return templates.TemplateResponse(
        request, "signup.html",
        _ctx(request,
             current_user=current_user,
             invitation=invitation,
             invite_token=invite if invitation else None,
             invitation_error=inv_error,
             email_value=(invitation["invited_email"] if invitation else None)),
    )


@app.post("/signup", response_class=HTMLResponse)
async def signup_post(
    request: Request,
    email: str = Form(...),
    password: str = Form(...),
    name: str = Form(""),
    role: str = Form("athlete"),
    invite_token: str = Form(""),
):
    email_norm = (email or "").strip().lower()
    name_clean = (name or "").strip()
    role_clean = role if role in ("athlete", "coach") else "athlete"

    # Резолвим приглашение если оно есть
    invitation, inv_error = _resolve_invitation(invite_token or None)
    if invite_token and inv_error:
        return templates.TemplateResponse(
            request, "signup.html",
            _ctx(request, error=inv_error,
                 email_value=email_norm, name_value=name_clean),
            status_code=400,
        )
    # Приглашение всегда для атлета — тренер не может прийти через invite
    if invitation:
        role_clean = "athlete"

    coach_user_id = invitation["coach_user_id"] if invitation else None

    def _err(msg, status=400):
        return templates.TemplateResponse(
            request, "signup.html",
            _ctx(request, error=msg,
                 email_value=email_norm, name_value=name_clean,
                 invitation=invitation, invite_token=invite_token or None,
                 selected_role=role_clean),
            status_code=status,
        )

    if "@" not in email_norm or len(email_norm) < 5:
        return _err("Похоже на невалидный email")
    if len(password) < 8:
        return _err("Пароль должен быть от 8 символов")
    existing = users_db.find_user_by_email(email_norm)
    if existing is not None:
        # Friendly hint если этот email уже привязан к Google
        if existing["auth_method"] == "google":
            return _err(
                "Этот email уже привязан к Google — войди через кнопку "
                "«Продолжить с Google» наверху", status=409,
            )
        return _err("Этот email уже зарегистрирован — попробуй войти", status=409)

    users_db.create_user(
        email_norm, password, name_clean,
        role=role_clean, coach_user_id=coach_user_id,
    )
    user_row = users_db.find_user_by_email(email_norm)
    users_db.touch_last_login(user_row["user_id"])

    if invitation:
        users_db.consume_invitation(invitation["invitation_token"], user_row["user_id"])

    # Email verification — отправляем письмо со ссылкой (или пишем в outbox.log
    # если SMTP не настроен). Не блокируем signup на отправку.
    verify_token = users_db.create_auth_token(
        user_row["user_id"], purpose="email_verify", ttl_hours=24 * 7,
    )
    base = str(request.base_url).rstrip("/")
    verify_url = f"{base}/verify-email?token={verify_token}"
    email_sender.send_email_verification(email_norm, name_clean, verify_url)

    # И атлет, и тренер после signup → /done (welcome).
    # Онбординг для атлета теперь отложенный — баннер на /done зовёт подключить
    # часы, но не блокирует продукт. Snowball-style: сначала ценность, потом setup.
    response = RedirectResponse("/done", status_code=303)
    _set_session(response, user_row)
    return response


def _safe_next_url(next_url: str | None) -> str:
    """Разрешаем редирект только на наш домен — чтобы не open-redirect.
    Принимаем абсолютные https://*.beatmetrics.ru/* и относительные /."""
    if not next_url:
        return "/done"
    nx = next_url.strip()
    if nx.startswith("/") and not nx.startswith("//"):
        return nx
    if (nx.startswith("https://beatmetrics.ru/")
            or nx.startswith("https://app.beatmetrics.ru/")
            or nx.startswith("https://www.beatmetrics.ru/")):
        return nx
    return "/done"


@app.get("/login", response_class=HTMLResponse)
async def login_get(request: Request, next: str | None = None):
    # НЕ делаем silent redirect для залогиненного — рендерим panel
    # «Уже вошли как X», симметрично с /signup. Пользователь может прийти
    # на /login осознанно (переключить аккаунт), и silent redirect путает.
    return templates.TemplateResponse(request, "login.html",
                                       _ctx(request, next_url=next))


@app.post("/login", response_class=HTMLResponse)
async def login_post(
    request: Request,
    email: str = Form(...),
    password: str = Form(...),
    next: str = Form(""),
):
    email_norm = (email or "").strip().lower()
    user_row = users_db.find_user_by_email(email_norm)
    # Friendly hint: если user зарегался через Google, пароля у него нет
    if user_row is not None and user_row["auth_method"] == "google":
        return templates.TemplateResponse(
            request, "login.html",
            _ctx(request,
                 error="Этот аккаунт зарегистрирован через Google — войди через кнопку «Продолжить с Google» выше",
                 email_value=email_norm, next_url=next or None),
            status_code=401,
        )
    if user_row is None or not users_db.verify_password(password, user_row["password_hash"]):
        return templates.TemplateResponse(
            request, "login.html",
            _ctx(request, error="Неверный email или пароль",
                 email_value=email_norm, next_url=next or None),
            status_code=401,
        )
    users_db.touch_last_login(user_row["user_id"])
    response = RedirectResponse(_safe_next_url(next), status_code=303)
    _set_session(response, user_row)
    return response


@app.post("/logout")
async def logout():
    # После logout — форма входа с баннером «Вы вышли». Без баннера
    # пользователь на shared-устройстве сомневается «а точно вышел?».
    response = RedirectResponse("/login?logged_out=1", status_code=303)
    _clear_session(response)
    return response


@app.get("/done", response_class=HTMLResponse)
async def done(request: Request):
    user = _get_current_user(request)
    if not user:
        return RedirectResponse("/signup", status_code=303)
    # Подтянем role из БД (в куки могли быть только базовые поля)
    user_row = users_db.find_user_by_id(user["user_id"])
    role = user_row["role"] if user_row else "athlete"

    extras = {"role": role}
    if role == "coach":
        # Тренер видит свои приглашения + атлетов
        extras["invitations"] = users_db.list_invitations_for_coach(user["user_id"])
        extras["athletes"] = users_db.list_athletes_for_coach(user["user_id"])
        host = str(request.base_url).rstrip("/")
        extras["invite_url_base"] = f"{host}/signup?invite="
    else:
        # Атлет: welcome + CTA-баннер на подключение (если 0 источников),
        # либо короткий статус (если есть подключённые)
        extras["connected_count"] = len(users_db.get_connected_providers(user["user_id"]))

    return templates.TemplateResponse(request, "done.html", _ctx(request, **extras))


# === Onboarding ===

def _provider_catalog() -> dict[str, dict]:
    """Каталог провайдеров для /onboarding/connect.
    Только активные (configured=True) попадают в primary-сетку.
    Провайдеры без живого API НЕ показываются как карточки —
    они есть в comeback-блоке "ещё на подходе" мелким текстом."""
    return {
        # === Primary: Strava (единственный с активным OAuth + мост для Apple) ===
        "strava": {
            "label": "Strava",
            "meta": "HR · темп · мост для Apple Watch и большинства Garmin",
            "configured": oauth_module.is_configured("strava"),
            "primary": True,
        },
        # === Active OAuth ===
        "polar": {
            "label": "Polar", "meta": "exercises · HRV · daily activity",
            "configured": oauth_module.is_configured("polar"),
        },
        "suunto": {
            "label": "Suunto", "meta": "workouts · FIT-файлы",
            "configured": oauth_module.is_configured("suunto"),
        },
        # === Apple — кликабельна, ведёт на Strava OAuth с from=apple ===
        "apple": {
            "label": "Apple Watch",
            "meta": "подключаем через Strava",
            "configured": True,
            "via_strava": True,
        },
        # === Garmin — pending, но показываем карточку с inline-формой notify ===
        "garmin": {
            "label": "Garmin Connect",
            "meta": "OAuth в pending",
            "pending": True,
            "notify_form": True,
        },
        # === Остальные pending — пока в compact-блоке внизу ===
        "coros":  {"label": "COROS", "pending": True, "_hidden": True},
        "trainingpeaks": {"label": "TrainingPeaks", "pending": True, "_hidden": True},
        "decathlon": {"label": "Decathlon Coach", "pending": True, "_hidden": True},
        "finalsurge": {"label": "Final Surge", "pending": True, "_hidden": True},
    }


@app.get("/onboarding/connect", response_class=HTMLResponse)
async def onboarding_connect(request: Request):
    user = _get_current_user(request)
    if not user:
        return RedirectResponse("/login", status_code=303)
    user_row = users_db.find_user_by_id(user["user_id"])
    if user_row and user_row["role"] == "coach":
        return RedirectResponse("/done", status_code=303)

    providers = _provider_catalog()
    connected = users_db.get_connected_providers(user["user_id"])
    return templates.TemplateResponse(
        request, "onboarding_connect.html",
        _ctx(request, providers=providers, connected_providers=connected),
    )


# === OAuth pre-screen ===

_OAUTH_SCOPES_HUMAN = {
    "strava": [
        "Активности (бег, вело, плавание)",
        "Пульс и зоны",
        "Профиль и базовые метрики",
    ],
    "polar": [
        "Тренировки и сессии",
        "Daily activity и HRV",
        "Базовая информация профиля",
    ],
    "suunto": [
        "Workouts и FIT-файлы",
        "Базовая информация профиля",
    ],
    "garmin": [
        "Активности (все виды спорта)",
        "Пульс, HRV, recovery",
        "Сон и Body Battery",
    ],
}


@app.get("/oauth/{provider}/preview", response_class=HTMLResponse)
async def oauth_preview(provider: str, request: Request):
    user = _get_current_user(request)
    if not user:
        return RedirectResponse("/login", status_code=303)
    if provider not in oauth_module.PROVIDERS:
        return RedirectResponse("/onboarding/connect?oauth_error=unknown",
                                status_code=303)
    if not oauth_module.is_configured(provider):
        return RedirectResponse(
            f"/onboarding/connect?oauth_error={provider}:not-configured",
            status_code=303,
        )

    # ?from=apple — пользователь пришёл по Apple-карточке.
    # Strava-OAuth тут используется как мост: Strava читает Apple Health
    # на iPhone, и наши синки идут через неё. Покажем это пользователю —
    # иначе он жмёт «Apple» и видит «Strava», и это выглядит как bait-and-switch.
    from_source = (request.query_params.get("from") or "").lower()
    via_label = None
    if from_source == "apple" and provider == "strava":
        via_label = "apple"

    user_row = users_db.find_user_by_id(user["user_id"])
    coach_name = None
    if user_row and user_row["coach_user_id"]:
        coach = users_db.find_user_by_id(user_row["coach_user_id"])
        if coach:
            coach_name = coach["name"] or coach["email"]

    return templates.TemplateResponse(
        request, "oauth_preview.html",
        _ctx(request,
             provider=provider,
             provider_label=oauth_module.PROVIDERS[provider]["label"],
             scope_read=_OAUTH_SCOPES_HUMAN.get(provider, ["Тренировки и сессии"]),
             coach_name=coach_name,
             via_label=via_label,
             # link для кнопки "Открыть провайдер" сохраняет from=
             connect_query="?from=" + from_source if from_source else "",
            ),
    )


# === Settings → Connections ===

_PROVIDER_LABELS = {
    "garmin": "Garmin Connect", "strava": "Strava",
    "polar": "Polar", "suunto": "Suunto", "coros": "COROS",
}


def _humanize_dt(value, is_unix_ts: bool = False) -> str | None:
    """ISO/unix → '2 минуты назад' / '12.08.2026'. None при отсутствии."""
    if not value:
        return None
    try:
        if is_unix_ts:
            dt = datetime.fromtimestamp(int(value), tz=timezone.utc)
        else:
            dt = datetime.fromisoformat(str(value).replace("Z", "+00:00"))
    except (ValueError, TypeError, OSError):
        return str(value)
    now = datetime.now(timezone.utc)
    delta = (now - dt).total_seconds()
    if -86400 < delta < 60:
        return "только что"
    if 60 <= delta < 3600:
        return f"{int(delta // 60)} мин назад"
    if 3600 <= delta < 86400:
        return f"{int(delta // 3600)} ч назад"
    if -86400 * 30 < delta < 86400 * 7:
        days = int(delta // 86400)
        return f"{abs(days)} дн {'назад' if days >= 0 else 'осталось'}"
    return dt.strftime("%d.%m.%Y")


@app.get("/settings/connections", response_class=HTMLResponse)
async def settings_connections(request: Request):
    user = _get_current_user(request)
    if not user:
        return RedirectResponse("/login", status_code=303)
    rows = users_db.list_connected_accounts(user["user_id"])

    now_ts = int(datetime.now(timezone.utc).timestamp())
    accounts = []
    for r in rows:
        exp = r["expires_at"]
        token_expired = bool(exp and int(exp) < now_ts)
        accounts.append({
            "provider": r["provider"],
            "external_user_id": r["external_user_id"],
            "connected_at_human": _humanize_dt(r["connected_at"]),
            "last_refresh_human": _humanize_dt(r["last_refresh_at"]),
            "expires_at_human": _humanize_dt(exp, is_unix_ts=True) if exp else None,
            "token_expired": token_expired,
        })

    return templates.TemplateResponse(
        request, "settings_connections.html",
        _ctx(request, accounts=accounts, provider_labels=_PROVIDER_LABELS),
    )


@app.post("/settings/connections/{provider}/disconnect")
async def settings_disconnect(provider: str, request: Request):
    user = _get_current_user(request)
    if not user:
        return RedirectResponse("/login", status_code=303)
    users_db.delete_connected_account(user["user_id"], provider)
    return RedirectResponse(
        f"/settings/connections?disconnected={provider}", status_code=303,
    )


# === Password reset / Email verify ===


@app.get("/forgot-password", response_class=HTMLResponse)
async def forgot_password_get(request: Request):
    return templates.TemplateResponse(request, "forgot_password.html", _ctx(request))


@app.post("/forgot-password", response_class=HTMLResponse)
async def forgot_password_post(request: Request, email: str = Form(...)):
    email_norm = (email or "").strip().lower()
    if "@" not in email_norm:
        return templates.TemplateResponse(
            request, "forgot_password.html",
            _ctx(request, error="Похоже на невалидный email", email_value=email_norm),
            status_code=400,
        )

    user_row = users_db.find_user_by_email(email_norm)
    # Не раскрываем существует email или нет — всегда рендерим "если есть, выслали"
    if user_row is not None:
        token = users_db.create_auth_token(
            user_row["user_id"], purpose="password_reset", ttl_hours=1,
        )
        base = str(request.base_url).rstrip("/")
        reset_url = f"{base}/reset-password?token={token}"
        email_sender.send_password_reset(email_norm, user_row["name"], reset_url)

    return templates.TemplateResponse(
        request, "forgot_password.html", _ctx(request, sent=True),
    )


@app.get("/reset-password", response_class=HTMLResponse)
async def reset_password_get(request: Request, token: str | None = None):
    if not token:
        return templates.TemplateResponse(
            request, "reset_password.html",
            _ctx(request, token_error="Ссылка некорректна — нет токена."),
            status_code=400,
        )
    row = users_db.find_auth_token(token, "password_reset")
    if row is None:
        return templates.TemplateResponse(
            request, "reset_password.html",
            _ctx(request, token_error="Ссылка истекла или уже использована."),
            status_code=400,
        )
    user_row = users_db.find_user_by_id(row["user_id"])
    return templates.TemplateResponse(
        request, "reset_password.html",
        _ctx(request, token=token, email=user_row["email"] if user_row else "?"),
    )


@app.post("/reset-password", response_class=HTMLResponse)
async def reset_password_post(
    request: Request,
    token: str = Form(...),
    password: str = Form(...),
    password2: str = Form(...),
):
    row = users_db.find_auth_token(token, "password_reset")
    if row is None:
        return templates.TemplateResponse(
            request, "reset_password.html",
            _ctx(request, token_error="Ссылка истекла или уже использована."),
            status_code=400,
        )
    user_row = users_db.find_user_by_id(row["user_id"])
    if user_row is None:
        return templates.TemplateResponse(
            request, "reset_password.html",
            _ctx(request, token_error="Аккаунт не найден."),
            status_code=400,
        )

    def _err(msg):
        return templates.TemplateResponse(
            request, "reset_password.html",
            _ctx(request, token=token, email=user_row["email"], error=msg),
            status_code=400,
        )

    if len(password) < 8:
        return _err("Пароль должен быть от 8 символов")
    if password != password2:
        return _err("Пароли не совпадают")

    users_db.update_password(user_row["user_id"], password)
    users_db.consume_auth_token(token)

    # Авто-логин после reset — пользователь сразу попадает на /done
    response = RedirectResponse("/done", status_code=303)
    _set_session(response, user_row)
    return response


@app.get("/verify-email", response_class=HTMLResponse)
async def verify_email(request: Request, token: str | None = None):
    if not token:
        return RedirectResponse("/login?verify_error=no_token", status_code=303)
    row = users_db.find_auth_token(token, "email_verify")
    if row is None:
        return RedirectResponse("/login?verify_error=expired", status_code=303)
    users_db.mark_email_verified(row["user_id"])
    users_db.consume_auth_token(token)
    # Если уже залогинен — на /done, иначе — на /login с успехом
    if _get_current_user(request):
        return RedirectResponse("/done?verified=1", status_code=303)
    return RedirectResponse("/login?verified=1", status_code=303)


@app.get("/settings/account", response_class=HTMLResponse)
async def settings_account_get(request: Request):
    user = _get_current_user(request)
    if not user:
        return RedirectResponse("/login", status_code=303)
    user_row = users_db.find_user_by_id(user["user_id"])
    if user_row is None:
        return RedirectResponse("/login", status_code=303)

    # Статистика для checklist «что будет удалено»
    with users_db.get_conn() as c:
        stats = {
            "cloud_activities": c.execute(
                "SELECT COUNT(*) FROM cloud_activities WHERE user_id=?",
                (user["user_id"],)).fetchone()[0],
            "connected_accounts": c.execute(
                "SELECT COUNT(*) FROM connected_accounts WHERE user_id=?",
                (user["user_id"],)).fetchone()[0],
            "coach_for_athletes": c.execute(
                "SELECT COUNT(*) FROM users WHERE coach_user_id=?",
                (user["user_id"],)).fetchone()[0],
        }
    return templates.TemplateResponse(
        request, "settings_account.html",
        _ctx(request, user_row=user_row, stats=stats),
    )


@app.post("/settings/account/delete")
async def settings_account_delete(
    request: Request,
    confirm_email: str = Form(...),
):
    user = _get_current_user(request)
    if not user:
        return RedirectResponse("/login", status_code=303)
    user_row = users_db.find_user_by_id(user["user_id"])
    if user_row is None:
        return RedirectResponse("/login", status_code=303)

    if (confirm_email or "").strip().lower() != user_row["email"].lower():
        # Re-render с ошибкой
        with users_db.get_conn() as c:
            stats = {
                "cloud_activities": c.execute("SELECT COUNT(*) FROM cloud_activities WHERE user_id=?", (user["user_id"],)).fetchone()[0],
                "connected_accounts": c.execute("SELECT COUNT(*) FROM connected_accounts WHERE user_id=?", (user["user_id"],)).fetchone()[0],
                "coach_for_athletes": c.execute("SELECT COUNT(*) FROM users WHERE coach_user_id=?", (user["user_id"],)).fetchone()[0],
            }
        return templates.TemplateResponse(
            request, "settings_account.html",
            _ctx(request, user_row=user_row, stats=stats,
                 delete_error="Email не совпадает с вашим — попробуйте ещё раз"),
            status_code=400,
        )

    # Подтверждение прошло — удаляем
    email = user_row["email"]
    name = user_row["name"]
    stats = users_db.delete_user(user["user_id"])
    # Финальное письмо (не блокируем на отправку — outbox-fallback в email_sender)
    email_sender.send_account_deleted(email, name, stats)

    response = RedirectResponse("/goodbye", status_code=303)
    _clear_session(response)
    return response


@app.get("/goodbye", response_class=HTMLResponse)
async def goodbye_page(request: Request):
    return templates.TemplateResponse(request, "goodbye.html", _ctx(request))


@app.post("/notify/{provider}")
async def notify_provider(provider: str, request: Request,
                           email: str = Form("")):
    """Подписка на уведомление «когда {provider} заработает»."""
    user = _get_current_user(request)
    if not user:
        return RedirectResponse("/login", status_code=303)
    allowed = {"garmin", "coros", "trainingpeaks", "decathlon", "finalsurge"}
    if provider not in allowed:
        return RedirectResponse(
            f"/onboarding/connect?oauth_error=notify:invalid-provider",
            status_code=303,
        )
    user_row = users_db.find_user_by_id(user["user_id"])
    email_value = (email or "").strip() or (user_row["email"] if user_row else "")
    result = users_db.request_provider_notify(
        email_value, provider, user_id=user["user_id"],
    )
    if result == "invalid":
        return RedirectResponse(
            f"/onboarding/connect?notify_error=invalid-email", status_code=303,
        )
    return RedirectResponse(
        f"/onboarding/connect?notify_{result}={provider}", status_code=303,
    )


@app.post("/settings/role/{new_role}")
async def settings_change_role(new_role: str, request: Request):
    """Переключение роли athlete↔coach. По умолчанию все signup-ы athlete;
    тренер может переключить с /done через кнопку «Я тренер»."""
    user = _get_current_user(request)
    if not user:
        return RedirectResponse("/login", status_code=303)
    if new_role not in ("athlete", "coach"):
        return RedirectResponse("/done?role_error=invalid", status_code=303)
    with users_db.get_conn() as c:
        c.execute("UPDATE users SET role = ? WHERE user_id = ?",
                  (new_role, user["user_id"]))
        c.commit()
    return RedirectResponse("/done", status_code=303)


@app.post("/coach/invite")
async def coach_invite(
    request: Request,
    invited_email: str = Form(""),
    note: str = Form(""),
):
    """Генерирует одноразовый invitation-token. Возвращает редирект на /done,
    где новая ссылка появится в списке."""
    user = _get_current_user(request)
    if not user:
        return RedirectResponse("/login", status_code=303)
    user_row = users_db.find_user_by_id(user["user_id"])
    if not user_row or user_row["role"] != "coach":
        return RedirectResponse("/done", status_code=303)
    users_db.create_invitation(
        coach_user_id=user["user_id"],
        invited_email=(invited_email or "").strip() or None,
        note=(note or "").strip() or None,
    )
    return RedirectResponse("/done#invites", status_code=303)


@app.get("/terms", response_class=HTMLResponse)
async def terms_page(request: Request):
    return _render_legal(request, "terms.md", "Пользовательское соглашение")


@app.get("/privacy", response_class=HTMLResponse)
async def privacy_page(request: Request):
    return _render_legal(request, "privacy.md", "Политика конфиденциальности")


def _render_legal(request: Request, filename: str, title: str) -> HTMLResponse:
    """Markdown legal-документ → HTML через стандартную lib `markdown`."""
    import markdown as md_lib
    path = BASE / "content" / filename
    raw = path.read_text(encoding="utf-8")
    html = md_lib.markdown(raw, extensions=["tables", "fenced_code"])
    return templates.TemplateResponse(
        request, "legal.html",
        _ctx(request, title=title, html_content=html),
    )


@app.get("/health")
async def health():
    return {"ok": True, "service": "signup"}
