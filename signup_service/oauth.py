"""OAuth-handlers для Strava / Polar / Suunto.

Endpoints:
    GET  /oauth/{provider}/connect    — редирект на authorize-URL провайдера
    GET  /oauth/{provider}/callback   — приём кода, обмен на access_token,
                                        сохранение в connected_accounts

Конфиг ключей из env:
    STRAVA_CLIENT_ID, STRAVA_CLIENT_SECRET
    POLAR_CLIENT_ID,  POLAR_CLIENT_SECRET
    SUUNTO_CLIENT_ID, SUUNTO_CLIENT_SECRET, SUUNTO_SUBSCRIPTION_KEY (optional)

Если ключ провайдера не задан — connect возвращает 503 с подсказкой.
Это позволяет подкатывать провайдеров по очереди, не ломая остальное.
"""
from __future__ import annotations

import base64
import hashlib
import os
import secrets
import sqlite3
from datetime import datetime, timezone
from urllib.parse import urlencode

import httpx
from cryptography.fernet import Fernet
from fastapi import APIRouter, HTTPException, Request, Response
from fastapi.responses import RedirectResponse

from . import db as users_db
from ._session import get_current_user

router = APIRouter(prefix="/oauth", tags=["oauth"])

# === Конфиг провайдеров ===

PROVIDERS: dict[str, dict] = {
    "strava": {
        "label": "Strava",
        "authorize_url": "https://www.strava.com/oauth/authorize",
        "token_url": "https://www.strava.com/oauth/token",
        "scope": "read,activity:read_all,profile:read_all",
        "client_id_env": "STRAVA_CLIENT_ID",
        "client_secret_env": "STRAVA_CLIENT_SECRET",
        "token_auth": "form",
        "extra_authorize": {"approval_prompt": "auto"},
    },
    "polar": {
        "label": "Polar",
        "authorize_url": "https://flow.polar.com/oauth2/authorization",
        "token_url": "https://polarremote.com/v2/oauth2/token",
        "scope": "accesslink.read_all",
        "client_id_env": "POLAR_CLIENT_ID",
        "client_secret_env": "POLAR_CLIENT_SECRET",
        "token_auth": "basic",
        "extra_authorize": {},
    },
    "suunto": {
        "label": "Suunto",
        "authorize_url": "https://cloudapi-oauth.suunto.com/oauth/authorize",
        "token_url": "https://cloudapi-oauth.suunto.com/oauth/token",
        "scope": "workout",
        "client_id_env": "SUUNTO_CLIENT_ID",
        "client_secret_env": "SUUNTO_CLIENT_SECRET",
        "token_auth": "form",
        "extra_authorize": {},
    },
}

STATE_COOKIE_PREFIX = "bm_oauth_state_"
STATE_TTL_SECONDS = 600  # 10 минут на завершение OAuth-флоу


# === Утилиты ===


def _provider_or_404(name: str) -> dict:
    cfg = PROVIDERS.get(name)
    if cfg is None:
        raise HTTPException(404, f"Unknown provider: {name}")
    return cfg


def _creds(name: str) -> tuple[str, str]:
    cfg = _provider_or_404(name)
    cid = (os.getenv(cfg["client_id_env"]) or "").strip()
    secret = (os.getenv(cfg["client_secret_env"]) or "").strip()
    return cid, secret


def _is_configured(name: str) -> bool:
    cid, secret = _creds(name)
    return bool(cid and secret)


def is_configured(name: str) -> bool:
    """Public alias — для использования из main.py при рендере /done."""
    return _is_configured(name)


def _callback_url(request: Request, provider: str) -> str:
    """Полный URL коллбэка. Зависит от base_url request (учитывает прокси-headers
    если nginx настроен с X-Forwarded-Proto)."""
    base = str(request.base_url).rstrip("/")
    return f"{base}/oauth/{provider}/callback"


def _fernet() -> Fernet:
    """Симметричное шифрование токенов. Ключ — SHA-256 от session-secret."""
    secret = os.getenv(
        "BEATMETRICS_SESSION_SECRET",
        "dev-secret-CHANGE-IN-PROD-please-use-32+chars",
    )
    digest = hashlib.sha256(secret.encode("utf-8")).digest()
    return Fernet(base64.urlsafe_b64encode(digest))


def encrypt_token(value: str) -> str:
    if not value:
        return ""
    return _fernet().encrypt(value.encode("utf-8")).decode("ascii")


def decrypt_token(enc: str) -> str:
    if not enc:
        return ""
    return _fernet().decrypt(enc.encode("ascii")).decode("utf-8")


def _save_connected_account(
    user_id: str, provider: str, token_data: dict, external_user_id: str | None
) -> None:
    """INSERT OR REPLACE в connected_accounts."""
    access = token_data.get("access_token", "")
    refresh = token_data.get("refresh_token", "")
    expires_at = token_data.get("expires_at")  # unix ts если есть
    if expires_at is None and token_data.get("expires_in"):
        expires_at = int(datetime.now(timezone.utc).timestamp()) + int(token_data["expires_in"])

    with users_db.get_conn() as c:
        c.execute(
            """
            INSERT INTO connected_accounts
                (user_id, provider, external_user_id,
                 access_token_enc, refresh_token_enc,
                 expires_at, scope, connected_at, last_refresh_at)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
            ON CONFLICT(user_id, provider) DO UPDATE SET
                external_user_id = excluded.external_user_id,
                access_token_enc = excluded.access_token_enc,
                refresh_token_enc = excluded.refresh_token_enc,
                expires_at = excluded.expires_at,
                scope = excluded.scope,
                last_refresh_at = excluded.last_refresh_at
            """,
            (user_id, provider, external_user_id,
             encrypt_token(access), encrypt_token(refresh),
             expires_at, token_data.get("scope"),
             users_db._now_iso(), users_db._now_iso()),
        )
        c.commit()


# === Routes ===


@router.get("/{provider}/connect")
async def connect(provider: str, request: Request):
    """Стартует OAuth flow — редиректит на authorize-URL провайдера."""
    user = get_current_user(request)
    if not user:
        return RedirectResponse("/login", status_code=303)

    cfg = _provider_or_404(provider)
    cid, _ = _creds(provider)
    if not cid:
        raise HTTPException(
            503,
            f"{cfg['label']} не настроен. "
            f"Положи {cfg['client_id_env']} и {cfg['client_secret_env']} в .env.",
        )

    # CSRF state — кладём в cookie, проверяем в callback
    state = secrets.token_urlsafe(16)
    params = {
        "client_id": cid,
        "redirect_uri": _callback_url(request, provider),
        "response_type": "code",
        "scope": cfg["scope"],
        "state": state,
        **cfg["extra_authorize"],
    }
    authorize_url = f"{cfg['authorize_url']}?{urlencode(params)}"

    response = RedirectResponse(authorize_url, status_code=302)
    response.set_cookie(
        f"{STATE_COOKIE_PREFIX}{provider}",
        f"{state}|{user['user_id']}",
        max_age=STATE_TTL_SECONDS,
        httponly=True,
        samesite="lax",
        secure=False,
    )
    return response


@router.get("/{provider}/callback")
async def callback(
    provider: str,
    request: Request,
    code: str | None = None,
    state: str | None = None,
    error: str | None = None,
):
    """Принимает code от провайдера, обменивает на access_token."""
    user = get_current_user(request)
    if not user:
        return RedirectResponse("/login", status_code=303)

    cfg = _provider_or_404(provider)
    cid, secret = _creds(provider)
    if not cid or not secret:
        raise HTTPException(503, f"{cfg['label']} не настроен (нет client_id/secret в .env)")

    if error:
        return RedirectResponse(
            f"/onboarding/connect?oauth_error={provider}:{error}", status_code=303
        )
    if not code:
        raise HTTPException(400, "Нет code в callback")

    # Проверяем state из cookie
    state_cookie = request.cookies.get(f"{STATE_COOKIE_PREFIX}{provider}", "")
    if "|" not in state_cookie:
        raise HTTPException(400, "Нет state-cookie — повтори подключение")
    saved_state, saved_user_id = state_cookie.split("|", 1)
    if saved_state != state:
        raise HTTPException(400, "State не совпал — возможно CSRF")
    if saved_user_id != user["user_id"]:
        raise HTTPException(400, "User-id в state не совпал с текущим")

    # Обменять code на token
    token_data = await _exchange_code(provider, code, request)

    external_user_id = _extract_external_user_id(provider, token_data)
    _save_connected_account(user["user_id"], provider, token_data, external_user_id)

    # Первый connect → ведём на /onboarding/period (выбор глубины истории).
    # Последующие подключения → обычный /onboarding/connect.
    connected_now = users_db.get_connected_providers(user["user_id"])
    if len(connected_now) == 1:
        next_url = f"/onboarding/period?just_connected={provider}"
    else:
        next_url = f"/onboarding/connect?connected={provider}"
    response = RedirectResponse(next_url, status_code=303)
    response.delete_cookie(f"{STATE_COOKIE_PREFIX}{provider}")
    return response


# === Token exchange ===


async def _exchange_code(provider: str, code: str, request: Request) -> dict:
    cfg = _provider_or_404(provider)
    cid, secret = _creds(provider)
    payload = {
        "grant_type": "authorization_code",
        "code": code,
        "redirect_uri": _callback_url(request, provider),
    }
    headers = {"Accept": "application/json"}
    auth = None

    if cfg["token_auth"] == "form":
        payload["client_id"] = cid
        payload["client_secret"] = secret
    elif cfg["token_auth"] == "basic":
        auth = (cid, secret)

    async with httpx.AsyncClient(timeout=20.0) as client:
        r = await client.post(cfg["token_url"], data=payload, headers=headers, auth=auth)
    if r.status_code >= 400:
        raise HTTPException(
            502, f"{cfg['label']} token exchange failed: HTTP {r.status_code} — {r.text[:200]}"
        )
    try:
        return r.json()
    except Exception as exc:
        raise HTTPException(502, f"{cfg['label']} вернул не-JSON: {r.text[:200]}") from exc


def _extract_external_user_id(provider: str, token_data: dict) -> str | None:
    """Каждый провайдер возвращает чуть разную структуру athlete/user info в ответе."""
    if provider == "strava":
        a = token_data.get("athlete") or {}
        return str(a.get("id") or "") or None
    if provider == "polar":
        return str(token_data.get("x_user_id") or "") or None
    if provider == "suunto":
        return str(token_data.get("user") or "") or None
    return None
