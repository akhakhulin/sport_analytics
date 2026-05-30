"""
Эвристика D: куда направить свободный текст от пользователя.

short feel-like → старый on_text_feedback (записывает feel в БД, без LLM)
вопросы/команды/длинный текст → JarvisAgent (читает БД, отвечает с Claude)
"""
from __future__ import annotations

import re

# Триггерные слова — если есть в тексте, это запрос к Jarvis (не feel-фидбек)
_JARVIS_TRIGGERS = (
    "?", "как", "что", "почему", "зачем", "когда", "где", "сколько",
    "какой", "какая", "какое", "какие", "проанализируй", "сделай",
    "покажи", "сравни", "дай", "найди", "посчитай", "оцени",
    "помоги", "расскажи", "объясни", "подскажи", "посоветуй",
    "проверь", "напиши", "составь", "построй", "рассчитай",
    "@jarvis",
)

# Феел-маркеры — короткие слова которые часто бывают в feedback после тренировки
# (если они есть и нет триггеров — точно feel)
_FEEL_MARKERS = (
    "норм", "ок", "тяжело", "легко", "плохо", "хорошо", "устал",
    "болит", "болело", "болела", "не спал", "сонный", "бодрый",
    "разбит", "огонь",
)

_LONG_TEXT_THRESHOLD = 80  # длиннее → всегда Jarvis


def is_jarvis_query(text: str) -> bool:
    """True — текст идёт в JarvisAgent. False — в старый feel-handler."""
    if not text:
        return False
    t = text.strip().lower()

    # Длинный текст — всегда Jarvis
    if len(t) > _LONG_TEXT_THRESHOLD:
        return True

    # Явный префикс — Jarvis
    if t.startswith(("/jarvis", "@jarvis", "?")):
        return True

    # Любой триггер — Jarvis
    # Используем поиск по словам, чтобы "как" не матчился внутри "какао"
    words = re.findall(r"[a-zа-яё]+", t)
    if any(trig in t for trig in _JARVIS_TRIGGERS if not trig.isalpha()):
        return True
    word_set = set(words)
    for trig in _JARVIS_TRIGGERS:
        if trig.isalpha() and trig in word_set:
            return True

    # Если в тексте есть feel-маркеры и нет триггеров — это feel-фидбек
    for marker in _FEEL_MARKERS:
        if marker in t:
            return False

    # Промежуточный случай: короткий, без триггеров, без feel-маркеров.
    # Например "вечер был странный". Отправляем в Jarvis — он лучше разберётся
    # чем feel-handler, который ждёт конкретные эмоции.
    return True
