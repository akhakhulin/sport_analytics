"""Shared session-cookie helpers — используются main.py, oauth.py, auth_google.py.

Cookie domain выставляется через env `BEATMETRICS_COOKIE_DOMAIN`:
- `.beatmetrics.ru` в проде → cookie виден И на app.beatmetrics.ru, И на beatmetrics.ru
  (нужно для SSO: Streamlit читает ту же сессию)
- пусто → host-only cookie (только на app.beatmetrics.ru) — fallback для dev
"""
from __future__ import annotations

import os

from fastapi import Request, Response
from itsdangerous import BadSignature, SignatureExpired, URLSafeTimedSerializer

SESSION_SECRET = os.getenv(
    "BEATMETRICS_SESSION_SECRET",
    "dev-secret-CHANGE-IN-PROD-please-use-32+chars",
)
SESSION_COOKIE = "bm_session"
SESSION_TTL_SECONDS = 30 * 24 * 3600
COOKIE_SECURE = os.getenv("BEATMETRICS_COOKIE_SECURE", "0").lower() in ("1", "true", "yes")
COOKIE_DOMAIN = (os.getenv("BEATMETRICS_COOKIE_DOMAIN") or "").strip() or None

serializer = URLSafeTimedSerializer(SESSION_SECRET, salt="bm-session-v1")


def get_current_user(request: Request) -> dict | None:
    token = request.cookies.get(SESSION_COOKIE)
    if not token:
        return None
    try:
        return serializer.loads(token, max_age=SESSION_TTL_SECONDS)
    except (BadSignature, SignatureExpired):
        return None


def set_session(response: Response, user_row) -> None:
    token = serializer.dumps(
        {
            "user_id": user_row["user_id"],
            "email": user_row["email"],
            "name": user_row["name"],
        }
    )
    response.set_cookie(
        SESSION_COOKIE,
        token,
        max_age=SESSION_TTL_SECONDS,
        httponly=True,
        samesite="lax",
        secure=COOKIE_SECURE,
        domain=COOKIE_DOMAIN,
    )


def clear_session(response: Response) -> None:
    """Удалить cookie. Делаем DOUBLE-DELETE — и с parent-domain, и host-only —
    на случай если у пользователя от прошлых сессий лежат обе версии
    (до SSO-миграции cookie ставилась host-only, после — с .beatmetrics.ru).
    Браузер чтит только matching domain, лишний delete безвреден."""
    # 1. С parent-domain (.beatmetrics.ru) — для текущих сессий
    if COOKIE_DOMAIN:
        response.delete_cookie(SESSION_COOKIE, domain=COOKIE_DOMAIN, path="/")
    # 2. Host-only (app.beatmetrics.ru) — для старых сессий до SSO
    response.delete_cookie(SESSION_COOKIE, path="/")
