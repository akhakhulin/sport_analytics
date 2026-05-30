"""BeatMetrics signup-сервис.

Минимальный FastAPI-сервис рядом со Streamlit-дашбордом, отвечающий за
регистрацию/вход пользователей по email+пароль + OAuth-подключение
устройств (Strava/Polar/Suunto/Garmin).

Запуск:
    .venv/Scripts/python.exe -m uvicorn signup_service.main:app \
        --host 127.0.0.1 --port 8502 --reload

В проде проксируется через nginx по `/signup`, `/login`, `/done` etc.
"""
# Загружаем .env из корня проекта ДО импорта оставшихся модулей,
# чтобы os.getenv() в oauth.py и _session.py подтянул нужные ключи.
from pathlib import Path

try:
    from dotenv import load_dotenv
    load_dotenv(Path(__file__).resolve().parent.parent / ".env")
except ImportError:
    # python-dotenv не установлен — env-переменные читаются как есть из shell
    pass
