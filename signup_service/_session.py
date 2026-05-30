"""Shared session-cookie helpers — используются main.py и oauth.py."""
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
    )
