"""Минимальный email-sender с двумя режимами.

Режим выбирается по env:
- SMTP_HOST + SMTP_USER + SMTP_PASS → реально отправляем через SMTP (TLS на 587 или SSL на 465)
- Иначе → пишем в logs/email_outbox.log в plain-формате
  (для dev и MVP, чтобы можно было видеть ссылки и тестировать flow)

Используется для:
- password reset link
- email verification link
"""
from __future__ import annotations

import logging
import os
import smtplib
import ssl
from email.message import EmailMessage
from pathlib import Path

log = logging.getLogger("email_sender")

SMTP_HOST = os.getenv("SMTP_HOST", "").strip()
SMTP_PORT = int(os.getenv("SMTP_PORT", "587") or "587")
SMTP_USER = os.getenv("SMTP_USER", "").strip()
SMTP_PASS = os.getenv("SMTP_PASS", "").strip()
SMTP_FROM = os.getenv("SMTP_FROM", "noreply@beatmetrics.ru").strip()
SMTP_USE_SSL = (os.getenv("SMTP_USE_SSL", "") or "").lower() in ("1", "true", "yes")

OUTBOX_LOG = Path(__file__).resolve().parent.parent / "logs" / "email_outbox.log"


def is_smtp_configured() -> bool:
    return bool(SMTP_HOST and SMTP_USER and SMTP_PASS)


def _write_to_outbox(to: str, subject: str, body: str) -> None:
    OUTBOX_LOG.parent.mkdir(parents=True, exist_ok=True)
    from datetime import datetime, timezone
    ts = datetime.now(timezone.utc).isoformat(timespec="seconds")
    with OUTBOX_LOG.open("a", encoding="utf-8") as f:
        f.write(f"\n=== {ts} ===\nTO: {to}\nSUBJECT: {subject}\n\n{body}\n")


def _send_smtp(to: str, subject: str, body: str) -> None:
    msg = EmailMessage()
    msg["From"] = SMTP_FROM
    msg["To"] = to
    msg["Subject"] = subject
    msg.set_content(body)
    if SMTP_USE_SSL:
        ctx = ssl.create_default_context()
        with smtplib.SMTP_SSL(SMTP_HOST, SMTP_PORT, context=ctx, timeout=15) as s:
            s.login(SMTP_USER, SMTP_PASS)
            s.send_message(msg)
    else:
        with smtplib.SMTP(SMTP_HOST, SMTP_PORT, timeout=15) as s:
            s.ehlo()
            s.starttls(context=ssl.create_default_context())
            s.login(SMTP_USER, SMTP_PASS)
            s.send_message(msg)


def send_email(to: str, subject: str, body: str) -> None:
    """Отправить (или залогировать) письмо. Никогда не бросает —
    проблема SMTP не должна валить signup/reset flow."""
    if not is_smtp_configured():
        _write_to_outbox(to, subject, body)
        log.info("email outbox (no SMTP) → %s: %s", to, subject)
        return
    try:
        _send_smtp(to, subject, body)
        log.info("email sent → %s: %s", to, subject)
    except Exception as exc:  # noqa: BLE001
        log.exception("smtp send failed, fallback to outbox")
        _write_to_outbox(to, f"[SMTP-FAIL] {subject}", body)


def send_password_reset(email: str, name: str | None, reset_url: str) -> None:
    body = (
        f"Привет{f', {name}' if name else ''}!\n\n"
        f"Кто-то (надеемся, что ты) запросил сброс пароля для аккаунта {email} в BeatMetrics.\n\n"
        f"Чтобы установить новый пароль, перейди по ссылке (она действует 1 час):\n"
        f"{reset_url}\n\n"
        f"Если ты не просил сброс — просто проигнорируй это письмо. Пароль не изменится.\n\n"
        f"— BeatMetrics\nhttps://beatmetrics.ru"
    )
    send_email(email, "BeatMetrics — сброс пароля", body)


def send_email_verification(email: str, name: str | None, verify_url: str) -> None:
    body = (
        f"Привет{f', {name}' if name else ''}!\n\n"
        f"Подтверди свой email, чтобы активировать аккаунт BeatMetrics:\n"
        f"{verify_url}\n\n"
        f"Ссылка действует 7 дней. Если не подтвердишь — аккаунт продолжит работать,\n"
        f"но мы не сможем отправлять тебе уведомления о синке и приглашения тренера.\n\n"
        f"— BeatMetrics"
    )
    send_email(email, "BeatMetrics — подтверди email", body)
