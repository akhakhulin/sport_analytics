# garmin_analytics

Локальная выгрузка и аналитика данных Garmin Connect.

## Что делает

- `garmin_sync.py` — логин в Garmin, инкрементальная выгрузка в SQLite:
  - **activities** — все тренировки + сводные метрики (HR, темп, TE, калории, VO2)
  - **daily_stats** — шаги, калории, RHR, стресс, body battery по дням
  - **sleep** — фазы сна, длительность, sleep score
  - **hrv** — HRV по ночам
- `analyze.py` — примеры аналитики на pandas

## Быстрый старт

```bash
# 1. Виртуальное окружение
python -m venv .venv
.venv\Scripts\activate          # Windows
# source .venv/bin/activate     # Linux/Mac

# 2. Зависимости
pip install -r requirements.txt

# 3. Настройки
copy .env.example .env
# Отредактировать .env — вписать email/password Garmin

# 4. Первая синхронизация (возьмёт год истории, 5–15 минут)
python garmin_sync.py

# 5. Посмотреть аналитику
python analyze.py
```

## Повторный запуск

При повторном `python garmin_sync.py`:
- активности — догружает только новее последней в БД
- daily_stats / sleep / hrv — проверяет последние 30 дней, добавляет отсутствующие

Можно поставить в планировщик Windows (раз в день).

## MFA

Если включена двухфакторка — при первом логине в консоли спросит код.
После успешного логина токены сохраняются в `./.garminconnect/`,
повторно пароль не потребуется (пока токен жив ~1 год).

## Структура БД

```
activities    — одна строка = одна тренировка (поле raw_json хранит полный ответ API)
daily_stats   — день
sleep         — день
hrv           — день
```

Поле `raw_json` во всех таблицах содержит полный JSON ответа Garmin —
если нужна метрика, которую не вынесли в отдельное поле, её можно
достать из raw_json.

## Что ещё можно вытащить

Библиотека [cyberjunky/python-garminconnect](https://github.com/cyberjunky/python-garminconnect)
имеет 130+ методов. Легко доращивается:

- `get_activity_details(activity_id)` — детали трека: GPS, пульс по секундам, лапы
- `get_training_readiness(date)` — готовность к тренировке
- `get_training_status(date)` — training load, VO2max trend
- `get_body_composition(start, end)` — вес, % жира, мышцы
- `get_stress_data(date)` — поминутный стресс
- `get_respiration_data(date)` — дыхание
- `get_spo2_data(date)` — SpO2

## Правовые риски

Это **неофициальное** API — работает через веб-интерфейс Garmin Connect.
Используй **только со своим аккаунтом**. При изменениях на стороне Garmin
библиотека может временно ломаться — обновлять пакет.

## Идеи для аналитики

- Корреляция HRV / sleep score → training effect
- Прогноз VO2max по тренировочной нагрузке
- Детект перетренированности (RHR ↑ + HRV ↓ + стресс ↑)
- Персональные темповые зоны из реальных треков
- Прогресс в силовых (повторения × вес по упражнениям)
