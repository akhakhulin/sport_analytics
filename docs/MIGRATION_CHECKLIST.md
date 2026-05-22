# Миграция на Windows Server 2022 — чеклист

**Цель:** перенести dev-окружение + Streamlit-дашборд + Telegram-бот + garmin_sync на выделенный Windows Server 2022 в облаке. Сохранить **полный workflow Claude Code + VS Code**, освободить локальный ноут от 24/7 нагрузки.

**Текущее состояние:** всё работает локально на Windows 11 (ноут). Минусы — нестабильный VPN-прокси, перерасход батареи, sync только когда ноут включён.

**Стратегия:** **параллельная работа 1-2 недели**, потом окончательное переключение. Локальный ноут остаётся как fallback.

---

## 0. Предварительная подготовка (до заказа VPS)

- [ ] Зафиксировать текущую rev в git (всё закоммичено и запушено)
- [ ] Сделать локальный бэкап БД: `data/garmin.db` (если есть, обычно SQLite-копия Turso)
- [ ] Экспортировать список зависимостей: `pip freeze > requirements-full.txt`
- [ ] Записать список Windows Task Scheduler задач (имена + что делают)
- [ ] Записать какие cookies/токены нужно перенести: `.env`, `cookies.txt`, Telegram bot token, Turso auth token, CLOUD_MASTER_KEY

## 1. Выбор и заказ VPS

### Рекомендуемые провайдеры (РФ, чтобы не зависеть от санкций)

| Провайдер | Win Server включён | Цена для нашей спеки | Особенности |
|---|---|---|---|
| **Selectel** | да | 4500-5500 ₽/мес | Хороший саппорт, дата-центры РФ, есть Vmware ESXi |
| **VK Cloud** | да | 4000-5000 ₽/мес | Большой, надёжный, привязан к VK ID |
| **Yandex Cloud** | да | 5000-7000 ₽/мес | Премиум-сегмент, есть managed services |
| **Timeweb Cloud** | да | 3500-4500 ₽/мес | Дешевле, простая панель |

### Рекомендуемая спецификация

```
ОС:      Windows Server 2022 Standard (с GUI, не Core)
CPU:     4 vCPU
RAM:     16 GB
Disk:    200 GB SSD
Сеть:    1 Gbps, белый IPv4
Регион:  Москва или СПб (низкая latency RDP)
```

**Почему 16 GB:** Whisper base ~2 ГБ + Streamlit ~1 ГБ + Chrome ~3 ГБ + VS Code ~2 ГБ + Python ~1 ГБ + запас 7 ГБ для пиков.

**Почему 200 GB:** видеоархив (~30 ГБ/год при 1-2 видео/мес) + БД-копии + system + page file.

- [ ] Заказать VPS, указать SSH/RDP доступ
- [ ] Получить IP, RDP-логин, RDP-пароль
- [ ] Сменить RDP-пароль на свой длинный сразу при первом входе

## 2. Подготовка Win Server 2022

### Первое подключение через RDP

- [ ] **Windows:** mstsc.exe → новый профиль с IP сервера → подключиться
- [ ] **macOS:** Microsoft Remote Desktop из App Store
- [ ] **Telegram:** можно для аварийных команд через бота позже

### Базовая настройка

- [ ] **Включить Desktop Experience** (если не предустановлен) — Win Server 2022 Standard обычно идёт с GUI. Проверить: рабочий стол, Explorer работают
- [ ] Сменить часовой пояс: `Set-TimeZone -Id "Russian Standard Time"`
- [ ] Установить русскую раскладку клавиатуры (для cyrillic в путях):
  - `Settings → Time & Language → Language → Add Russian`
- [ ] Отключить IE Enhanced Security Configuration (мешает Chrome скачивать):
  - Server Manager → Local Server → IE Enhanced Security Configuration → Off (для Admin)
- [ ] Windows Update — установить все critical updates, перезагрузиться
- [ ] Создать структуру папок:
  ```
  C:\1с_dev\garmin_analytics\     <- репозиторий
  C:\Лекции по подготовке\Youtube\ <- видео
  C:\backups\                     <- БД и cookies бэкапы
  ```

### Безопасность (КРИТИЧНО)

- [ ] **Сменить дефолтный RDP-порт** с 3389 на нестандартный (например 53389):
  - `Set-ItemProperty -Path 'HKLM:\System\CurrentControlSet\Control\Terminal Server\WinStations\RDP-Tcp' -Name 'PortNumber' -Value 53389`
  - Перезагрузить + открыть новый порт в firewall, закрыть 3389
- [ ] **Windows Firewall**: разрешить только нужное:
  - RDP (новый порт) — только с твоего IP, если можно
  - 80, 443 — для Streamlit nginx (входящий)
  - Всё остальное закрыть
- [ ] **NLA для RDP** (Network Level Authentication) — включить, защищает от bruteforce
- [ ] Установить **fail2ban-аналог** для Windows — RDPGuard или EvlWatcher (банит IP после 5 неудачных попыток)
- [ ] **Включить BitLocker** на диске данных (опционально, если боишься физического доступа)
- [ ] **Антивирус Defender** — включён по умолчанию, проверить

## 3. Установка dev-стека

### Базовые инструменты

```powershell
# Запустить PowerShell от имени администратора
# Установить winget если нет (обычно есть в Server 2022)
winget install --id Microsoft.WindowsTerminal
winget install --id Git.Git
winget install --id Python.Python.3.13
winget install --id Microsoft.VisualStudioCode
winget install --id Google.Chrome
winget install --id Gyan.FFmpeg
winget install --id Anthropic.Claude  # если есть пакет, иначе VSIX
```

- [ ] Установить **Git** — после установки настроить:
  - `git config --global user.name "Артём Хахулин"`
  - `git config --global user.email "khakhulinar@gmail.com"`
- [ ] Установить **Python 3.13** через winget — добавить в PATH
- [ ] Установить **VS Code** + extensions:
  - Python
  - Pylance
  - Ruff
  - GitLens
  - **Claude Code** (главное)
- [ ] Установить **Chrome** — для скачивания cookies + просмотра дашборда локально
- [ ] Установить **ffmpeg** через winget — нужен для Whisper

### Аутентификация Claude Code

- [ ] Открыть VS Code → Command Palette → Claude: Sign In
- [ ] Использовать тот же аккаунт Anthropic что и локально
- [ ] Проверить подписку активна (Max plan)

### Опционально

- [ ] **Telegram Desktop** — для отправки команд боту с того же сервера (необязательно)
- [ ] **Yandex Disk Desktop** или **rclone** — для бэкапов в облако
- [ ] **GitHub CLI (`gh`)** — `winget install GitHub.cli`, потом `gh auth login`

## 4. Перенос проекта

### Клонирование репо

```powershell
cd C:\1с_dev\
git clone https://github.com/akhakhulin/sport_analytics.git garmin_analytics
cd garmin_analytics
```

- [ ] Проверить что `git clone` прошёл (все папки на месте)
- [ ] Проверить `git status` (clean)
- [ ] Проверить `git log` (последний коммит виден)

### Перенос секретов (КРИТИЧНО, через зашифрованный канал)

**Что переносим:**
- `.env` — Turso URL/auth_token, Telegram bot token, CLOUD_MASTER_KEY
- `cookies.txt` — для yt-dlp
- `garminconnect/garmin_tokens.json` — токены Garmin (опционально, синканёт сам)
- `data/garmin.db` — локальная копия БД (опционально, libsql сам подтянет из Turso)

**Способ переноса:**

**ВАРИАНТ A — через RDP clipboard (для текстовых файлов):**
- Скопировать содержимое `.env` локально → Ctrl+C → вставить в текстовый файл на сервере → сохранить

**ВАРИАНТ B — через зашифрованный архив:**
1. Локально: `7z a -p<пароль> secrets.7z .env cookies.txt garminconnect/`
2. Закинуть на сервер через RDP shared folder или через Telegram (на свой канал)
3. На сервере распаковать с тем же паролем
4. Удалить архив

**ВАРИАНТ C — через защищённое облако:**
- Залить в Yandex Disk с паролем → скачать на сервере → удалить

⚠️ **НЕ передавать секреты через незашифрованные каналы** (email, обычный Telegram-чат без шифрования)

- [ ] `.env` на месте, открыт через notepad — все переменные читаются
- [ ] `cookies.txt` в `C:\Users\Administrator\Downloads\cookies.txt`
- [ ] Никаких секретов в git — `git status` clean

### Virtual environment

```powershell
cd C:\1с_dev\garmin_analytics
python -m venv .venv
.\.venv\Scripts\Activate.ps1
python -m pip install --upgrade pip
pip install -r requirements.txt
pip install yt-dlp faster-whisper  # если не в requirements.txt
```

- [ ] venv активируется без ошибок
- [ ] `pip list` показывает все нужные пакеты
- [ ] `python -c "from faster_whisper import WhisperModel"` — без ошибок

### Проверка БД

```powershell
python -c "import db; conn = db.connect(); print('OK:', conn.execute('SELECT COUNT(*) FROM activities').fetchone())"
```

- [ ] Подключение к Turso работает (`OK: (953,)` или больше)
- [ ] libsql sync прошёл без ошибок (может занять 10-30 сек первый раз)

## 5. Streamlit-дашборд

### Локальный запуск (проверка)

```powershell
.\.venv\Scripts\Activate.ps1
streamlit run dashboard.py
```

- [ ] Открывается http://localhost:8501
- [ ] Видны данные за май 2026 (последние тренировки)
- [ ] CSS грузится корректно (sport_icons, цвета)
- [ ] Сравнение периодов открывается

### Публикация наружу через nginx (опционально, если не на Streamlit Cloud)

Если хочешь чтобы дашборд был доступен жене/тренеру/другим атлетам по https://your-domain.ru:

- [ ] Установить **nginx**: `winget install nginx.nginx`
- [ ] Купить домен (если нет): regru.ru / spaceweb.ru / yandex.cloud DNS
- [ ] Привязать домен к IP сервера (DNS A-запись)
- [ ] Получить SSL-сертификат: **win-acme** (Let's Encrypt для Windows) или Cloudflare
- [ ] Настроить nginx reverse proxy:
  ```nginx
  server {
      listen 443 ssl;
      server_name your-domain.ru;
      ssl_certificate     C:/certs/fullchain.pem;
      ssl_certificate_key C:/certs/privkey.pem;
      location / {
          proxy_pass http://127.0.0.1:8501;
          proxy_http_version 1.1;
          proxy_set_header Upgrade $http_upgrade;
          proxy_set_header Connection "upgrade";
          proxy_set_header Host $host;
      }
  }
  ```
- [ ] Открыть порт 443 в firewall Windows
- [ ] Streamlit запустить как **Windows Service** (через NSSM):
  ```powershell
  nssm install StreamlitDashboard "C:\1с_dev\garmin_analytics\.venv\Scripts\streamlit.exe" "run dashboard.py --server.headless true"
  nssm start StreamlitDashboard
  ```

**Альтернатива:** оставить дашборд на **Streamlit Community Cloud** (уже работает), на сервере только sync + bot. Тогда nginx не нужен.

## 6. Garmin sync

### Telemetry sync (если оставляем локальный)

- [ ] Скопировать содержимое `cloud_sync/` — уже в репо, ничего не нужно делать
- [ ] **Альтернатива:** оставить sync через GitHub Actions (уже работает)
- [ ] **Локальный sync через Task Scheduler:**
  - Создать задачу через `tools/install_watchdog.py` или вручную
  - Триггер: ежедневно 04:00
  - Действие: `C:\1с_dev\garmin_analytics\.venv\Scripts\python.exe -m cloud_sync.sync_all`
  - User: Administrator (или сервисная учётка)
  - Run whether user logged in or not: да

- [ ] Запустить вручную: `python -m cloud_sync.sync_all` — проверить что отрабатывает
- [ ] Проверить через 24ч что cron сработал (логи + БД обновилась)

## 7. Telegram-бот

- [ ] Скопировать содержимое `bot/` — уже в репо
- [ ] Проверить `.env` есть `TELEGRAM_BOT_TOKEN`
- [ ] Запустить вручную: `python bot/main.py` — проверить что бот отвечает
- [ ] Зарегистрировать как **Windows Service** через NSSM:
  ```powershell
  nssm install GarminBot "C:\1с_dev\garmin_analytics\.venv\Scripts\python.exe" "bot/main.py"
  nssm set GarminBot AppDirectory "C:\1с_dev\garmin_analytics"
  nssm set GarminBot AppStdout "C:\1с_dev\garmin_analytics\logs\bot.log"
  nssm set GarminBot AppStderr "C:\1с_dev\garmin_analytics\logs\bot.err"
  nssm set GarminBot AppRotateFiles 1
  nssm start GarminBot
  ```
- [ ] **Watchdog** — `bot/watchdog.ps1` через Task Scheduler каждые 5 мин (как сейчас, тот же путь)
- [ ] Перезагрузить сервер → проверить что бот сам стартует

## 8. Whisper / yt-dlp

- [ ] Запустить тестово: `tools/youtube_download.ps1 "<тестовый URL>"` — скачать на сервер
- [ ] Запустить транскрипт: `python tools/video_analyze.py <путь> --out test_run`
- [ ] Проверить что:
  - ffmpeg найден
  - faster-whisper модель base скачалась (~150 МБ)
  - Whisper отрабатывает на 25-мин видео за ~5-10 мин
- [ ] Удалить test_run/

## 9. Бэкапы

- [ ] **БД-бэкап** в Yandex Disk / rclone:
  - Раз в сутки `data/garmin.db` копируется в облако
  - Через Task Scheduler 03:00
- [ ] **`.env` бэкап** в зашифрованный архив раз в неделю
- [ ] **knowledge/ + plans/** — уже в git, ничего не нужно
- [ ] **video_analysis/transcripts/** — опционально, восстанавливаемо

## 10. Параллельное тестирование (1-2 недели)

**НЕ выключай локальный ноут пока работает сервер.**

- [ ] День 1-3: на сервере только sync (через cron) + бэкап БД. Дашборд работает через Streamlit Cloud как сейчас
- [ ] День 4-7: подключиться через RDP, проверить Claude Code workflow:
  - Скачать тестовое видео
  - Сделать Whisper
  - Создать md-саммари
  - Закоммитить и запушить
- [ ] День 8-10: запустить бота на сервере (выключить локального!) — проверить что отвечает, watchdog работает
- [ ] День 11-14: ежедневная работа полностью на сервере, ноут — только тренировки

## 11. Окончательное переключение

После 2 недель параллельной работы:

- [ ] Выключить локальный garmin sync (отменить Task Scheduler задачу)
- [ ] Выключить локальный Telegram-бот
- [ ] Локальный VS Code оставить как fallback на случай отказа сервера
- [ ] Локальные cookies и `.env` НЕ удалять (бэкап)
- [ ] Обновить документацию: где теперь работает что

## 12. Откат (если что-то пойдёт не так)

- [ ] Локальный ноут НЕ трогать — все скрипты остаются на месте
- [ ] Включить локальный Garmin sync обратно через Task Scheduler
- [ ] Запустить локальный бот вручную / через Task Scheduler
- [ ] Сервер оставить включённым для разбора причин

---

## Стоимость владения

| Статья | Сумма |
|---|---|
| VPS Win Server (Selectel, 16 ГБ, 4 vCPU, 200 ГБ) | 4500-5500 ₽/мес |
| Anthropic Claude Max | $200/мес (~18 000 ₽) — как сейчас |
| Домен (опционально, если своя публикация) | 200-500 ₽/год |
| SSL (Let's Encrypt) | 0 ₽ |
| Yandex Disk Pro 200 ГБ для бэкапов | 200 ₽/мес |
| **Итого дельта vs локально** | **~5000 ₽/мес** |

## Главные риски

| Риск | Митигация |
|---|---|
| Сервер уходит под санкции / отключается | Бэкапы в Yandex Disk + локальный fallback. Миграция к другому хостеру за 2-3 дня |
| Утечка RDP-пароля | Длинный пароль + смена порта + RDPGuard + 2FA через MS Authenticator (опционально) |
| Атака через Streamlit | nginx reverse proxy + минимум открытых портов + auth.py если публично |
| Высокий счёт Anthropic | Лимит на API budget в Claude Console + мониторинг через `/cost` |
| Cookies протухают раз в час | Авто-обновление через расширение Get Cookies (раз в день перезаливать на сервер) |

## Что НЕ переносить

- **`.venv/`** — пересоздать на сервере (Windows vs Windows совместимо, но ради чистоты)
- **`__pycache__/`** — авто-генерируется
- **`tmp/`, `logs/`** — пересоздаются
- **`build/`, `dist/`** — артефакты от PyInstaller, не используются
- **`video_analysis/`** — большие транскрипты, лучше восстановить из видео если понадобятся

## Открытые вопросы (требуют решения до миграции)

1. **Где Streamlit будет публиковаться?** Оставляем на Streamlit Cloud или поднимаем на своём nginx с доменом?
2. **Свой домен или нет?** Если нет — RDP только для меня, дашборд на Streamlit Cloud (бесплатно).
3. **Какая учётка для сервисов?** Administrator или сервисная без интерактивного входа?
4. **Backup-стратегия БД** — раз в сутки в Yandex Disk достаточно? Или нужна репликация в реальном времени?
5. **Cookies refresh** — раз в день руками через RDP-Chrome или автоматизировать через Selenium?

---

*Документ обновляется по мере выполнения. Финальная версия = живая инструкция для возможной переустановки.*
