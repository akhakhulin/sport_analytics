# BeatMetrics — project guidelines for Claude

## Что это

SaaS-аналитика тренировок для endurance-атлетов (лыжи / бег / вело) и их тренеров.
Аггрегирует данные из Garmin / Strava / Polar / Suunto / COROS через OAuth.

## Архитектура

```
beatmetrics.ru/                       Landing (static HTML + nginx)
beatmetrics.ru/dashboard/             Streamlit dashboard (analytics)
app.beatmetrics.ru/*                  FastAPI signup_service
                                      (auth, OAuth, onboarding, settings)
SSO через cookie bm_session on .beatmetrics.ru (HMAC itsdangerous).
```

Backend: SQLite (`data/garmin.db` или Turso libsql replica), Python 3.13, venv в `.venv/`.
Все persistent сервисы — через Windows Task Scheduler с `LogonType=S4U`
(переживают RDP logoff): `GarminAtomik-Dashboard`, `-Nginx`, `-SignupService`,
`-CloudSyncWorker`.

## Brand

- Primary: `#3c3489` (purple)
- Tagline: «тренируйся осознанно»
- Лого: `docs/Beatmetrics_logo/` (SVG + brand-guide)
- Brand-иконки часов: `signup_service/static/icons/` (Garmin/Polar/Suunto/COROS/Apple/Strava)

## ⚠️ Правила работы

### UX (обязательно)

**Перед commit любой UI-правки** — вызови `/ux-review <путь-к-template-или-URL>`.
Это slash-команда, которая запустит `ux-designer` subagent. Он:
- Проанализирует страницу по 7 принципам (1 CTA, state-aware UI, no tech debt
  in UI, no дубликаты, mobile-first, a11y AA, конверсия-метрика)
- Вернёт замечания с приоритетом P0/P1/P2
- 🔴 P0 — обязательно фиксить ДО commit'а
- 🟡 P1 fast — fix если <15 мин, иначе в backlog

Это не опция. Я (main agent) регулярно пропускаю UX-фейлы, которые
user отлавливает после commit'а (см. memory `feedback_ux_self_audit.md`).
Subagent-инспектор закрывает эту дыру.

Когда **не нужно** /ux-review: bug-fix без UI, опечатки, чисто backend.

### Git

- Push требует выключенного VPN (`unset HTTP_PROXY HTTPS_PROXY`)
- Дробить коммит на куски ≤5 МБ (мобильный uplink обрывает большие)
- См. memory: `feedback_git_push_through_vpn.md`

### Sessions / cookies

- `BEATMETRICS_SESSION_SECRET` сейчас **default** (`"dev-secret-CHANGE-IN-PROD-..."`).
  Менять только в окно maintenance: cмена секрета invalidate всех сессий
  И сломает Fernet-расшифровку OAuth-токенов (Strava/Polar) — придётся переподключать.
- Cookie domain: `.beatmetrics.ru` (для SSO между Streamlit и FastAPI).

### Перезапуск сервисов

После Python-изменений Streamlit/FastAPI кешируют модули в памяти.
Restart обязателен:
```
schtasks /End /TN GarminAtomik-SignupService
schtasks /Run /TN GarminAtomik-SignupService
```
То же для `GarminAtomik-Dashboard` и `GarminAtomik-Nginx`.

CSS / Jinja2 templates подхватываются на лету — restart не нужен.

### Email

Если `SMTP_HOST/USER/PASS` в .env — реальная отправка через TLS.
Иначе — fallback в `logs/email_outbox.log` (для dev / MVP). См. `signup_service/email_sender.py`.

## Внешние ссылки

- GitHub: https://github.com/akhakhulin/sport_analytics
- Prod: https://beatmetrics.ru / https://app.beatmetrics.ru
- Google OAuth: Cloud Console project `BeatMetrics Auth`, client_id начинается на `849804291904-`
- Strava: live, токены в `connected_accounts` (Fernet-encrypted)
- Polar / Suunto / Garmin Dev / COROS — заявки в работе, см. todo

## Внутренние artifacts

- Мокап онбординга: `docs/onboarding_mockup.html` (эталон)
- Setup Google: `docs/google_signin_setup.md`
- Скриншоты разработки: `docs/screenshots/` (gitignored)
- Memory: `~/.claude/projects/.../memory/MEMORY.md` (индекс) — обязательно читать релевантные feedback-правила
