"""Настройки бота: загрузка из .env, пути к файлам."""
from __future__ import annotations

import os
from pathlib import Path

from dotenv import load_dotenv

# Загружаем .env из корня проекта
PROJECT_ROOT = Path(__file__).resolve().parent.parent
load_dotenv(PROJECT_ROOT / ".env")

# === Telegram ===
TELEGRAM_BOT_TOKEN = os.environ.get("TELEGRAM_BOT_TOKEN", "").strip()
TELEGRAM_CHAT_ID_ENV = os.environ.get("TELEGRAM_CHAT_ID", "").strip()

# === Garmin / БД ===
ATHLETE_ID = os.environ.get("ATHLETE_ID", "akhakhulin").strip()
DB_PATH = PROJECT_ROOT / os.environ.get("DB_PATH", "./data/garmin.db").lstrip("./").lstrip("/")

# === Файлы плана ===
PLAN_EXCEL = PROJECT_ROOT / "plans" / "2026_05_may_schedule_v2.xlsx"
PLAN_SHEET = "Тренировки списком"

# === Расписание ===
ACTIVITY_POLL_INTERVAL_MIN = 30
MORNING_HOUR_RANGE = (6, 11)  # отправлять утренний отчёт только в этом окне локального времени

# === Tolerance ===
ZONE_COMPLIANCE_THRESHOLD = 0.70  # ≥70% времени в плановой зоне = соответствует

# === Логирование ===
LOG_DIR = PROJECT_ROOT / "logs"
LOG_DIR.mkdir(exist_ok=True)
LOG_FILE = LOG_DIR / "bot.log"


def assert_token() -> None:
    if not TELEGRAM_BOT_TOKEN:
        raise SystemExit(
            "TELEGRAM_BOT_TOKEN не задан в .env. Получи токен через @BotFather и добавь в .env."
        )
