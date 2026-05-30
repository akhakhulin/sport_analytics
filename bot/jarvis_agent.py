"""
JarvisAgent — обёртка над claude-agent-sdk, использует OAuth от Claude Code
(твоя Max-подписка) вместо API key.

ВАЖНО: использование подписки в стороннем боте формально нарушает Consumer
Terms (Section 3, automated access). С 15 июня 2026 будет официально через
Agent SDK credits — тогда переключимся.

Архитектура:
  - SDK подцепляет credentials из ~/.claude/.credentials.json автоматически.
  - per-chat session_id хранится в data/jarvis_threads/<chat_id>.json для
    resume — Claude помнит весь предыдущий разговор.
  - Read-only tools на старте (Read, Grep, Glob, WebFetch). Без Bash/Edit.
  - permission_mode='acceptEdits' (формально безопасно при ограниченных tools).
"""
from __future__ import annotations

import asyncio
import json
import logging
import os
from datetime import date
from pathlib import Path

from claude_agent_sdk import (
    AssistantMessage,
    ClaudeAgentOptions,
    ResultMessage,
    SystemMessage,
    TextBlock,
    query,
)

from . import config

log = logging.getLogger(__name__)

# === Конфиг ===
MODEL = os.environ.get("ANTHROPIC_MODEL", "claude-sonnet-4-6").strip()
# Read-only tools на старте (без Bash/Edit/Write — безопаснее в боте)
ALLOWED_TOOLS = ["Read", "Grep", "Glob", "WebFetch", "WebSearch"]

THREADS_DIR = config.PROJECT_ROOT / "data" / "jarvis_threads"
SPEND_FILE = config.PROJECT_ROOT / "data" / "jarvis_spend.json"

MAX_THREAD_TURNS = 30   # ограничение глубины разговора

# Системные подсказки кладём как append_system_prompt — добавляются к Claude Code system
_SYSTEM_APPEND = """
Ты сейчас работаешь в режиме Jarvis — отвечаешь пользователю через Telegram-бот.

# Особенности канала
- Это Telegram, не VS Code. Ответы короткие, без длинных полотен текста.
- Не используй ANSI, не пиши длинные блок-цитаты. Markdown работает (жирный, курсив, `code`).
- Не предлагай пользователю действия которые он сам должен сделать — он сейчас не за компьютером, скорее всего с телефона.

# Инструменты — только чтение
- Доступны: Read, Grep, Glob, WebFetch, WebSearch.
- НЕТ доступа к Bash, Edit, Write — даже если очень хочется.
- Если задача требует Bash/Edit — скажи пользователю «нужно сделать в VS Code», без подробных инструкций.

# Контекст пользователя
- Атлет akhakhulin (Артём), КМС-кандидат по лыжам, мастер по бегу к 2027.
- Реальные физиозоны (важно!):
  * Бег: LTHR=178, HRmax=187. Garmin занижает на 4 удара.
  * Велосипед: LTHR≈153, HRmax≈170 (РАЗНЫЕ от беговых).
- Не используй беговые HR-зоны для вело-активностей.
- Локальная БД Garmin в data/garmin.db, схема активностей — table `activities`.
- Знакомься с памятью через Read C:\\Users\\Administrator\\.claude\\projects\\c--1--dev-garmin-analytics\\memory\\
"""


# === Persistence ===


def _thread_path(chat_id: int) -> Path:
    THREADS_DIR.mkdir(parents=True, exist_ok=True)
    return THREADS_DIR / f"{chat_id}.json"


def _load_thread(chat_id: int) -> dict:
    """Возвращает {'session_id': str|None, 'turns': int, 'total_cost_usd': float}."""
    path = _thread_path(chat_id)
    if not path.exists():
        return {"session_id": None, "turns": 0, "total_cost_usd": 0.0}
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except Exception:  # noqa: BLE001
        return {"session_id": None, "turns": 0, "total_cost_usd": 0.0}


def _save_thread(chat_id: int, data: dict) -> None:
    _thread_path(chat_id).write_text(
        json.dumps(data, ensure_ascii=False, indent=2),
        encoding="utf-8",
    )


# === Spend tracking (нативно из ResultMessage.total_cost_usd) ===


def _record_usage(chat_id: int, result_cost: float) -> None:
    """Запись расхода. Через подписку реальные деньги не списываются, но трекаем."""
    if not result_cost:
        return
    # Per-thread
    thread = _load_thread(chat_id)
    thread["total_cost_usd"] = round(thread.get("total_cost_usd", 0.0) + result_cost, 6)
    _save_thread(chat_id, thread)
    # Global daily
    SPEND_FILE.parent.mkdir(parents=True, exist_ok=True)
    try:
        data = json.loads(SPEND_FILE.read_text(encoding="utf-8")) if SPEND_FILE.exists() else {}
    except Exception:  # noqa: BLE001
        data = {}
    key = date.today().isoformat()
    day = data.setdefault(key, {"requests": 0, "cost_usd": 0.0})
    day["requests"] += 1
    day["cost_usd"] = round(day["cost_usd"] + result_cost, 6)
    SPEND_FILE.write_text(json.dumps(data, indent=2), encoding="utf-8")


def today_spend_usd() -> float:
    if not SPEND_FILE.exists():
        return 0.0
    try:
        data = json.loads(SPEND_FILE.read_text(encoding="utf-8"))
        return data.get(date.today().isoformat(), {}).get("cost_usd", 0.0)
    except Exception:  # noqa: BLE001
        return 0.0


# === Главный класс ===


class JarvisAgent:
    def __init__(self) -> None:
        self.model = MODEL
        log.info(
            "JarvisAgent инициализирован (claude-agent-sdk), model=%s, tools=%s",
            MODEL, ALLOWED_TOOLS,
        )

    def query_sync(self, chat_id: int, user_msg: str) -> str:
        """Синхронная обёртка для вызова из telegram-handler (он async)."""
        return asyncio.run(self.query_async(chat_id, user_msg))

    async def query_async(self, chat_id: int, user_msg: str) -> str:
        thread = _load_thread(chat_id)
        session_id = thread.get("session_id")

        options = ClaudeAgentOptions(
            cwd=str(config.PROJECT_ROOT),
            model=self.model,
            allowed_tools=ALLOWED_TOOLS,
            permission_mode="default",
            resume=session_id,
            max_turns=8,
        )

        answer_parts: list[str] = []
        new_session_id: str | None = None
        cost_usd = 0.0
        had_error = False

        try:
            async for msg in query(prompt=user_msg, options=options):
                if isinstance(msg, SystemMessage) and msg.subtype == "init":
                    new_session_id = msg.data.get("session_id")
                elif isinstance(msg, AssistantMessage):
                    for block in msg.content:
                        if isinstance(block, TextBlock):
                            answer_parts.append(block.text)
                elif isinstance(msg, ResultMessage):
                    cost_usd = float(getattr(msg, "total_cost_usd", 0.0) or 0.0)
                    if msg.is_error:
                        had_error = True
                        log.warning("Jarvis result error: %s", msg.subtype)
        except Exception as exc:
            log.exception("Jarvis query failed")
            return f"⚠️ Ошибка SDK: {exc}"

        # Обновляем thread state
        thread["session_id"] = new_session_id or session_id
        thread["turns"] = thread.get("turns", 0) + 1
        _save_thread(chat_id, thread)
        _record_usage(chat_id, cost_usd)

        log.info(
            "Jarvis chat=%d session=%s turns=%d cost=$%.4f%s",
            chat_id,
            (new_session_id or session_id or "?")[:8],
            thread["turns"],
            cost_usd,
            " (had_error)" if had_error else "",
        )

        answer = "\n".join(answer_parts).strip()
        return answer or "(пустой ответ от Jarvis)"

    def reset_thread(self, chat_id: int) -> None:
        path = _thread_path(chat_id)
        if path.exists():
            path.unlink()


# Совместимость с прежним API (handlers.py зовёт agent.query)
JarvisAgent.query = JarvisAgent.query_sync  # type: ignore[assignment]
