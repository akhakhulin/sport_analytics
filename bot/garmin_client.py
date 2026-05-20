"""Обёртка для Garmin Connect клиента — переиспользует .garminconnect токены."""
from __future__ import annotations

import logging
import os
from pathlib import Path
from typing import Optional

from garminconnect import Garmin

from . import config

log = logging.getLogger("bot.garmin")


def login() -> Optional[Garmin]:
    """Логин в Garmin Connect (использует кэш токенов из .garminconnect/).

    Совместимо с тем как это делает garmin_sync.py — передаём путь в tokenstore,
    библиотека сама подгрузит сохранённые токены или сделает свежий логин.
    """
    email = os.environ.get("GARMIN_EMAIL", "").strip()
    password = os.environ.get("GARMIN_PASSWORD", "").strip()
    tokens_rel = os.environ.get("GARMIN_TOKENS_DIR", "./.garminconnect")
    tokens_dir = (config.PROJECT_ROOT / tokens_rel.lstrip("./").lstrip("/")).resolve()
    tokens_dir.mkdir(parents=True, exist_ok=True)

    if not email and not password:
        log.error("GARMIN_EMAIL / GARMIN_PASSWORD не заданы в .env")
        return None

    try:
        client = Garmin(email or "", password or "")
        client.login(tokenstore=str(tokens_dir))
        log.info("Garmin клиент готов (через tokenstore)")
        return client
    except Exception as e:
        log.exception(f"Garmin login failed: {e}")
        return None
