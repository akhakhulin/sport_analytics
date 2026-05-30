"""Google Sign-In через OAuth 2.0 + OpenID Connect.

Endpoints:
    GET /auth/google/login    — старт flow, редирект на Google
    GET /auth/google/callback — приём кода, создание/логин user

Конфиг (через .env):
    GOOGLE_CLIENT_ID
    GOOGLE_CLIENT_SECRET
    GOOGLE_REDIRECT_BASE   — необязательно; иначе берём request.base_url

Логика: если email уже в users → залогинить. Если нет → создать (без пароля,
с пометкой email_verified_at = now, потому что Google email уже verified).
"""
from __future__ import annotations

import os
import secrets

from authlib.integrations.starlette_client import OAuth
from fastapi import APIRouter, HTTPException, Request
from fastapi.responses import RedirectResponse

from . import db as users_db
from ._session import set_session as _set_session

router = APIRouter(prefix="/auth/google", tags=["auth-google"])

# Глобальный OAuth-клиент; .env подгружается через signup_service/__init__.py
oauth = OAuth()
oauth.register(
    name="google",
    server_metadata_url="https://accounts.google.com/.well-known/openid-configuration",
    client_kwargs={"scope": "openid email profile"},
)


def _is_configured() -> bool:
    return bool(
        (os.getenv("GOOGLE_CLIENT_ID") or "").strip()
        and (os.getenv("GOOGLE_CLIENT_SECRET") or "").strip()
    )


def is_configured() -> bool:
    """Public alias — для проверки из шаблонов / main.py."""
    return _is_configured()


def _client():
    """Получить настроенный клиент с актуальными credentials из env."""
    cid = (os.getenv("GOOGLE_CLIENT_ID") or "").strip()
    secret = (os.getenv("GOOGLE_CLIENT_SECRET") or "").strip()
    if not cid or not secret:
        raise HTTPException(
            503,
            "Google Sign-In не настроен. "
            "Положи GOOGLE_CLIENT_ID и GOOGLE_CLIENT_SECRET в .env.",
        )
    oauth.google.client_id = cid
    oauth.google.client_secret = secret
    return oauth.google


def _callback_url(request: Request) -> str:
    base = (os.getenv("GOOGLE_REDIRECT_BASE")
            or str(request.base_url).rstrip("/"))
    return f"{base}/auth/google/callback"


@router.get("/login")
async def google_login(request: Request):
    client = _client()
    redirect_uri = _callback_url(request)
    # authlib сам положит state в session — нам нужен StarletteMiddleware-session.
    # Но мы используем cookie-based session через itsdangerous,
    # поэтому передадим state в cookie вручную.
    state = secrets.token_urlsafe(16)
    response = await client.authorize_redirect(
        request, redirect_uri, state=state,
    )
    response.set_cookie(
        "bm_google_state", state,
        max_age=600, httponly=True, samesite="lax", secure=False,
    )
    return response


@router.get("/callback")
async def google_callback(request: Request, code: str | None = None,
                          state: str | None = None, error: str | None = None):
    if error:
        return RedirectResponse(f"/login?google_error={error}", status_code=303)
    if not code:
        return RedirectResponse("/login?google_error=no_code", status_code=303)

    saved_state = request.cookies.get("bm_google_state", "")
    if not saved_state or saved_state != state:
        return RedirectResponse("/login?google_error=state_mismatch", status_code=303)

    client = _client()
    try:
        token = await client.authorize_access_token(request)
    except Exception as exc:  # noqa: BLE001
        return RedirectResponse(
            f"/login?google_error=token_exchange:{type(exc).__name__}",
            status_code=303,
        )

    userinfo = token.get("userinfo") or {}
    email = (userinfo.get("email") or "").strip().lower()
    name = (userinfo.get("name") or "").strip() or None
    email_verified = bool(userinfo.get("email_verified"))

    if not email:
        return RedirectResponse("/login?google_error=no_email", status_code=303)
    if not email_verified:
        return RedirectResponse("/login?google_error=email_not_verified", status_code=303)

    # Существующий user → log in
    existing = users_db.find_user_by_email(email)
    if existing is None:
        # Создаём с рандом-паролем (не используется для входа,
        # но колонка NOT NULL — заполняем заглушкой)
        random_password = secrets.token_urlsafe(32)
        users_db.create_user(email, random_password, name=name, role="athlete")
        # Помечаем email_verified_at вручную (create_user не выставляет)
        with users_db.get_conn() as c:
            c.execute(
                "UPDATE users SET email_verified_at = datetime('now') WHERE email = ?",
                (email,),
            )
            c.commit()
        user_row = users_db.find_user_by_email(email)
    else:
        user_row = existing

    users_db.touch_last_login(user_row["user_id"])

    response = RedirectResponse("/done", status_code=303)
    response.delete_cookie("bm_google_state")
    _set_session(response, user_row)
    return response
