# Jarvis: интеграция в @RoadToMC_bot — план на 15 июня 2026

**Триггер для активации:** скажи Claude «запускаем Jarvis в основной бот» или «продолжаем то что отложили на 15 июня».

> **СТАТУС (актуально на 27.05.2026):** Jarvis **уже работает** — с 27.05.2026 через
> отдельный бот **@Jarvis_Klode_bot** + `tg_bridge.py` (subprocess `claude --print`,
> биллинг через Max x5). Задача на 15.06 — НЕ «первый запуск», а **консолидация**:
> перенести Jarvis в основной @RoadToMC_bot через Agent SDK Credits, чтобы был 1 бот
> вместо 2. Подробности: `memory/project_jarvis_postponed_2026-06-15.md`.

## Контекст

26 мая 2026 написали `bot/jarvis_agent.py` для разговорного режима @RoadToMC_bot
через Anthropic SDK. Упёрлись в баланс ($0 API credits, РФ-карты не принимают).

27 мая обошли это **временным решением** — отдельный @Jarvis_Klode_bot на
`tg_bridge.py` (subprocess `claude --print`, работает на Max-подписке без API credits).

Решение для **консолидации в один бот** — ждать **15 июня 2026**, когда Anthropic
запустит **Agent SDK Credits** для Max-подписки. Это даст $100/мес квоты на
программный доступ через SDK, покроет наш юзкейс с запасом.

Источник: https://support.claude.com/en/articles/15036540-use-the-claude-agent-sdk-with-your-claude-plan

## Что НЕ переделывать (уже готово)

- `bot/jarvis_agent.py` — обёртка над claude-agent-sdk (последняя редакция,
  до этого был anthropic SDK — обе версии лежат в git history).
- `bot/jarvis_routing.py` — эвристика D (короткий feel-фидбек vs Jarvis-вопрос),
  14/14 тестов passed.
- `bot/handlers.py` — `on_text_feedback` уже маршрутизирует через
  `jarvis_routing.is_jarvis_query` в `_handle_jarvis_query`.
- `bot/main.py` — `cmd_jarvis_reset` и `cmd_jarvis_spend` зарегистрированы.
- `.streamlit/secrets.toml` — bcrypt-логин для дашборда.
- **@Jarvis_Klode_bot + `C:\Claude_Projects\bots\beatmetrics-jarvis\tg_bridge.py`** —
  рабочий резервный путь, оставить как fallback пока не подтвердим интеграцию.

> **ВНИМАНИЕ к путям:** проект переехал с `C:\1с_dev\garmin_analytics` на
> **`c:\Claude_Projects\garmin_analytics`**. Все команды ниже уже поправлены под новый
> путь. Если встретишь `C:\1с_dev\...` где-то ещё — это устаревший путь.

## Пошаговый план на 15 июня

### 1. Проверить что Agent SDK Credits активны

```powershell
# Открыть console.anthropic.com → Plans & Billing → видим "Agent SDK Credits: $X / $100"
# Или попробовать smoke-test сразу (ниже шаг 4)
```

Если ещё не запустилось — продолжаем жить на @Jarvis_Klode_bot, ждём или проверяем official docs.

### 2. Убедиться что OAuth-токен Claude Code актуален

```powershell
Get-Item C:\Users\Administrator\.claude\.credentials.json | Select-Object Length, LastWriteTime
# Если LastWriteTime старее месяца — открыть Claude Code extension в VS Code,
# он сам обновит при следующем запуске.
```

### 3. (Если использовали anthropic SDK версию) Вернуть обратно claude-agent-sdk

`bot/jarvis_agent.py` должен использовать `from claude_agent_sdk import query, ClaudeAgentOptions`.
Если в файле `import anthropic` — посмотреть git log:

```bash
git log --oneline bot/jarvis_agent.py
git show <commit-c-claude-agent-sdk>:bot/jarvis_agent.py > bot/jarvis_agent.py
```

### 4. Smoke-test через Python

```powershell
cd C:\Claude_Projects\garmin_analytics
.venv\Scripts\python.exe -c "
import asyncio
from bot.jarvis_agent import JarvisAgent

async def main():
    a = JarvisAgent()
    print(await a.query_async(46006295, 'Привет, скажи коротко: ты работаешь через Max или через API credits?'))

asyncio.run(main())
"
```

**Ожидаемо:** ответ без `Credit balance is too low`. Если ответ есть — Agent SDK Credits активны, можно интегрировать Jarvis в основной бот.

### 5. Перезапустить @RoadToMC_bot чтобы подхватить обновлённый jarvis_agent.py

```powershell
Stop-ScheduledTask -TaskName "GarminAtomik-Bot"
Start-Sleep -Seconds 3
Get-CimInstance Win32_Process -Filter "Name='python.exe'" | Where-Object { $_.CommandLine -like '*bot.main*' } | ForEach-Object { Stop-Process -Id $_.ProcessId -Force }
Remove-Item C:\Claude_Projects\garmin_analytics\logs\bot.lock -ErrorAction SilentlyContinue
Start-ScheduledTask -TaskName "GarminAtomik-Bot"
Start-Sleep -Seconds 10
Get-Content C:\Claude_Projects\garmin_analytics\logs\bot.log -Tail 10
```

### 6. End-to-end тест через Telegram

В Telegram написать @RoadToMC_bot:

- «привет» — должно молчать (короткий feel-маркер, не Jarvis)
- «болит колено» — должно молчать (feel-маркер)
- «что у меня по плану на завтра?» — должно идти в Jarvis, прийти ответ от Claude
- `/jarvis_spend` — покажет $ за день
- `/jarvis_reset` — сбросит thread-контекст

### 7. После успешной интеграции — отключить временный путь

Когда @RoadToMC_bot отвечает как Jarvis — @Jarvis_Klode_bot и
`BeatmetricsJarvis-Bridge` Task можно остановить (или оставить резервом):

```powershell
# Опционально, только после подтверждения что основной бот работает:
Stop-ScheduledTask -TaskName "BeatmetricsJarvis-Bridge"
Disable-ScheduledTask -TaskName "BeatmetricsJarvis-Bridge"
```

### 8. Если что-то не работает

Проверить логи: `logs/bot.log`, `logs/bot_bat.log`.

Распространённые ошибки:
- `Credit balance is too low` — Agent SDK Credits ещё не активны, остаёмся на @Jarvis_Klode_bot
- `CLINotFoundError` — claude CLI не в PATH, перезапустить bat с обновлённым `$env:Path`
- `Permission denied` — auto-mode классификатор в SDK блокирует, добавить explicit `permission_mode='acceptEdits'` (уже есть)
- `Tool not found` — SDK ожидает другой формат `allowed_tools`, см. issue tracker SDK

## Запасной план (если Agent SDK Credits не сработали)

Самый надёжный fallback — **продолжать на @Jarvis_Klode_bot** (`tg_bridge.py`), он уже работает.
Прочие варианты сравнения путей — см. `memory/project_jarvis_postponed_2026-06-15.md`:
- Polza.ai / ProxyAPI — российский агрегатор, оплата МИР, ~200₽/мес
- B1 + WSL2 — Channels через CLI + Linux подсистема, 0₽ но 4-6 ч работы
- AWS Bedrock / GCP Vertex — нужна виртуалка с не-РФ картой

## Связанная инфра уже стоит на сервере

- Node.js v24, npm 11, Bun 1.3.14, Claude CLI 2.1.150
- Marketplace claude-plugins-official добавлен
- Plugin fakechat установлен (для теста Channels, можно удалить: `claude plugin uninstall fakechat@claude-plugins-official`)
- Все Python deps: `anthropic` 0.104.1, `claude-agent-sdk` 0.2.87, `python-telegram-bot` 22.7, `bcrypt` 5.0.0
- @Jarvis_Klode_bot + `C:\Claude_Projects\bots\beatmetrics-jarvis\tg_bridge.py` (Task `BeatmetricsJarvis-Bridge`, AtStartup, S4U)
