---
description: Pre-commit UX-аудит страницы или экрана. Вызывает ux-designer subagent на конкретный template / URL / скриншот. Использовать ОБЯЗАТЕЛЬНО перед commit'ом любой UI-правки.
---

# /ux-review

Запусти `ux-designer` subagent для UX-аудита **конкретной страницы / template / скриншота**, который указан в `$ARGUMENTS`.

## Что делать

1. Если в `$ARGUMENTS` указан **путь к template** (`signup_service/templates/X.html`) — прочитай его, плюс CSS, плюс соответствующий route в `main.py`.
2. Если указан **URL** (`https://app.beatmetrics.ru/...` или `/signup`) — сделай playwright-скриншот в desktop (1440×900) и mobile (390×844), сохрани в `docs/screenshots/ux-review/`.
3. Если указан **скриншот** (путь к PNG) — используй его как есть.

## Вызов subagent

После сбора входных данных вызови:

```
Agent(
  subagent_type="ux-designer",
  description="UX review of <страница>",
  prompt="""
  Сделай UX-review страницы <название>.

  ЦЕЛЬ страницы: <одно предложение — что должен сделать пользователь>.
  СОСТОЯНИЕ пользователя при просмотре: <залогинен / нет / с подключенным Strava / etc.>

  Source-файлы:
  - Template: <путь>
  - Route: <путь:строки в main.py>
  - CSS: <путь:строки или весь файл>

  Screenshots:
  - Desktop: <путь>
  - Mobile: <путь>

  Что особенно проверить:
  - State-aware UI (не показываем форму при сессии и т.п.)
  - Один primary CTA (не дублируем)
  - Нет tech debt в UI («SSO в работе», «DEV PROGRAM»)
  - Mobile-layout не ломается
  - Accessibility: контраст AA, touch ≥44px, alt-text

  Формат ответа — стандартный (✅ хорошо / 🔴 P0 / 🟡 P1 / 🟢 P2 / 🎯 рекомендация).
  """
)
```

## Что делать с ответом

1. Перенеси ВСЕ **🔴 P0** замечания в TodoWrite — обязательно фиксить до commit'а
2. **🟡 P1** — если фикс не больше 15 минут, тоже сделать сейчас
3. **🟢 P2** — добавить в polish backlog
4. После применения фиксов — **повторно сделать скриншоты** и показать пользователю результат

## Когда НЕ применять

- Bug-fix без изменения UI (sync-воркер, OAuth, миграция БД)
- Опечатки, цвета, единичные мелочи
- Pure backend (роуты без templates)
