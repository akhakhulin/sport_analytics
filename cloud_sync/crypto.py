"""
AES-GCM шифрование секретов «облачных» атлетов (Garmin password + tokens).

Мастер-ключ — 32 байта, base64-урл-сейф. Хранится:
- локально (для админ-CLI):  CLOUD_MASTER_KEY в .env
- в воркере (GitHub Actions):  тот же CLOUD_MASTER_KEY в repo Secrets

В Turso хранится только зашифрованный шифротекст (с nonce + tag),
закодированный base64. Без мастер-ключа расшифровать невозможно.

Формат шифротекста (base64-url-safe):
    [12 байт nonce] + [N байт ciphertext + tag]
"""

from __future__ import annotations

import base64
import os
import secrets

from cryptography.hazmat.primitives.ciphers.aead import AESGCM


_KEY_BYTES = 32  # AES-256


def generate_master_key() -> str:
    """Сгенерировать новый мастер-ключ. Положить в env как CLOUD_MASTER_KEY."""
    return base64.urlsafe_b64encode(secrets.token_bytes(_KEY_BYTES)).decode("ascii")


def _load_key() -> bytes:
    raw = os.getenv("CLOUD_MASTER_KEY", "").strip()
    if not raw:
        raise RuntimeError(
            "CLOUD_MASTER_KEY не задан. Сгенерируй: "
            "`python -m cloud_sync.admin init-key`"
        )
    try:
        key = base64.urlsafe_b64decode(raw + "=" * (-len(raw) % 4))
    except Exception as exc:
        raise RuntimeError(f"CLOUD_MASTER_KEY невалидный base64: {exc}") from exc
    if len(key) != _KEY_BYTES:
        raise RuntimeError(
            f"CLOUD_MASTER_KEY должен быть {_KEY_BYTES} байт, "
            f"а распакован в {len(key)}."
        )
    return key


def encrypt(plaintext: str) -> str:
    """Зашифровать строку → base64."""
    key = _load_key()
    aes = AESGCM(key)
    nonce = secrets.token_bytes(12)
    ct = aes.encrypt(nonce, plaintext.encode("utf-8"), associated_data=None)
    return base64.urlsafe_b64encode(nonce + ct).decode("ascii")


def decrypt(ciphertext_b64: str) -> str:
    """Расшифровать base64 → исходная строка."""
    key = _load_key()
    aes = AESGCM(key)
    blob = base64.urlsafe_b64decode(
        ciphertext_b64 + "=" * (-len(ciphertext_b64) % 4)
    )
    if len(blob) < 13:
        raise ValueError("Шифротекст слишком короткий.")
    nonce, ct = blob[:12], blob[12:]
    pt = aes.decrypt(nonce, ct, associated_data=None)
    return pt.decode("utf-8")
