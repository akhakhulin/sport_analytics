# 📦 Sportsmen Analytics — Пакет для разработчика

> **Дата сборки:** 29 апреля 2026
> **Текущая версия ТЗ:** 1.3
> **Статус:** прототипы согласованы, готово к реализации

---

## 🗂 Структура артефактов

### Документация (Markdown)

| Файл | Что внутри |
|------|-----------|
| [`SPECIFICATION.md`](./SPECIFICATION.md) | **Главное ТЗ** — общая архитектура, компоненты, API, дизайн-токены, план разработки |
| [`SPECIFICATION_period_comparison.md`](./SPECIFICATION_period_comparison.md) | **★ NEW v1.3** — детальная спецификация функции сравнения периодов |

### Интерактивные прототипы (HTML)

| Файл | Назначение | Версия |
|------|-----------|--------|
| [`sportsmen_analytics_v3_variant_a.html`](./sportsmen_analytics_v3_variant_a.html) | **★ Главный прототип дашборда** — Вариант A с панелью детализации на всю ширину | v3 (актуальная) |
| [`period_comparison_simple.html`](./period_comparison_simple.html) | **★ Сравнение периодов** — упрощённый интерфейс с date-picker и фильтром | v1 (актуальная) |
| [`drilldown_time_variant_a.html`](./drilldown_time_variant_a.html) | Чистый блок детализации Время — режим «Сумма» без переключателей | v1 |
| `sportsmen_analytics_v2_fixed.html` | Промежуточная версия (с фиксами CV, вкладок-пилюль) | history |
| `sportsmen_analytics_interactive.html` | Первая версия прототипа | history |

### Дизайн-ассеты

| Файл | Назначение |
|------|-----------|
| [`sport_icons_pack.html`](./sport_icons_pack.html) | Витрина SVG-иконок видов спорта (16 шт) с примерами кода и маппингом Garmin/Strava |
| [`sport_icons_svg/`](./sport_icons_svg/) | Папка с отдельными SVG-файлами иконок (16 файлов 256×256) + index.html |
| [`sport_icons_svg_pack.zip`](./sport_icons_svg_pack.zip) | ZIP-архив всех иконок одним файлом для скачивания |

---

## 🚀 С чего начать разработку

### 1. Прочитать главное ТЗ
**[`SPECIFICATION.md`](./SPECIFICATION.md)** — здесь описано всё:
- Архитектура страницы (§3)
- Все компоненты по разделам (§4)
- Backend API (§6)
- TypeScript типы (§7)
- State management (§8)
- Файловая структура (§10)
- Дизайн-токены (§11)
- План спринтов (§12)
- Acceptance Criteria (§13)

### 2. Открыть прототипы
- **Главный дашборд:** `sportsmen_analytics_v3_variant_a.html`
- **Сравнение периодов:** `period_comparison_simple.html`

Прототипы — это **источник истины**. При расхождениях между ТЗ и прототипом — приоритет у прототипа.

### 3. Скачать иконки
Распакуйте `sport_icons_svg_pack.zip` и используйте SVG-файлы напрямую через `<img>` или `<use>` (см. `sport_icons_pack.html` для примеров).

---

## 📋 План работы по спринтам

### Спринт 1 — Каркас (1 неделя)
- Vite + React + TypeScript + ESLint/Prettier
- Дизайн-токены (`tokens.css`)
- AppShell с layout
- Общие компоненты: `Block`, `Toast`, `Modal`, `GearMenu`, `Sparkline`
- Zustand + Tanstack Query

### Спринт 2 — Sidebar (3-4 дня)
- UserHeader, AthleteSelect
- PeriodFilter с custom-range
- ActivityPills
- GroupingToggle
- SyncStatusBlock

### Спринт 3 — KPI Grid + Drilldown (1 неделя)
- KpiGrid с равной шириной
- KpiCard с состояниями
- CSS-стрелка вниз для активной KPI
- DrilldownPanel + DistanceDrilldown
- DrilldownChart с осью Y и сеткой
- CvBadge с 4 уровнями
- DistanceInsight с правилами

### Спринт 4 — Recovery, PMC, Zones (1 неделя)
- RecoveryBlock с 3 RecoveryCard
- PmcBlock
- LthrControl
- HrZonesBars + HrZonesDonut

### Спринт 5 — Weekly + Insights + Bottom row (1 неделя)
- WeeklyZonesGrid с метаданными
- AiInsights
- PowerCurve + ComplianceBlock

### Спринт 6 — Сравнение периодов (1 неделя) ★ NEW v1.3
- Маршрут `/comparison`
- PeriodInputBlock + ActivityFilterBlock
- PeriodComparisonCard + ResultCard
- Эндпоинт `GET /api/dashboard/comparison`
- URL-синхронизация состояния
- Edge cases и валидация

### Спринт 7 — Полировка (3-5 дней)
- Адаптив (планшет, мобильный)
- Loading / error / empty states
- Локализация (RU + готовность к EN)
- localStorage для настроек
- Lighthouse audit (≥ 85 Performance, ≥ 90 A11y)

---

## 🎨 Технологический стек

```
Framework:       React 18 + TypeScript
Bundler:         Vite
Styling:         CSS Modules или Tailwind
Charts:          Recharts (базово) + D3.js (PMC)
State:           Zustand
Data fetching:   Tanstack Query
Date:            date-fns
Icons:           Lucide React (общие) + sport-icons (свои SVG)
Тесты:           Vitest + React Testing Library
Mocks:           MSW (для разработки без бэка)
```

---

## 🔑 Ключевые решения и принципы

### Дизайн
- **Минимум формы, максимум данных** — каждое нажатие должно давать инсайт
- **Цветовая семантика везде** — зелёный = хорошо, красный = плохо, серый = нейтрально
- **Дельты обязательны** — никогда не показывать значение без контекста (vs прошлый период)
- **CV/inline-инсайты** — числа не существуют сами по себе, всегда с интерпретацией

### Архитектура
- **KPI равной ширины (1fr × 4)** — никогда не сжимаются при раскрытии
- **Детализация — отдельная панель под KPI** — на всю ширину Main
- **Вкладки = пилюли в строке заголовка** — единый паттерн (как `5 зон / Seiler`)
- **Шестерёнка в каждом блоке** — для редких настроек, чтобы не загромождать UI

### Логика сравнения периодов
- **Дефолт «Все активности»** — самый частый сценарий
- **Авто-переключение в `Выбрать` при клике по пилюле** — без потери выбора
- **Inline-предупреждение при асимметрии** — но не блокирует тренера
- **URL-shareable** — все параметры в адресной строке

---

## ⚠ Известные требования

### Бэкенд
- ⚠ **CV считать только по неделям с активностью** (km > 0). Иначе получается невозможное >100%.
- ⚠ **Не возвращать прочерк `—`** — если данных для сравнения нет, поле `delta: null`. Фронт сам решит, что показывать.
- ⚠ **`weekStartLabel` приходит готовым с бэка** в формате `Mar 30`. Фронт не парсит даты.
- ⚠ **Округление чисел** — 1 знак после запятой (`94.5`, `+16.4`). Никаких `3.81854...`.

### Фронт
- ⚠ **Только одна KPI раскрыта одновременно**
- ⚠ **Только одна шестерёнка открыта одновременно**
- ⚠ **CSS-стрелка вниз** обязательна для активной KPI (визуальная связь с панелью детализации)
- ⚠ **Анимация slideDown 0.3s** при раскрытии панели

---

## 🔗 Контакты

- **Владелец продукта:** Артём Хахулин (тренер)
- **Backend стэк:** Turso (облако)
- **Атлет для тестов:** akhakhulin (147 активностей за 91 день)

---

## 📝 Открытые вопросы (нужно согласовать)

1. **PDF-генерация** — фронт (jsPDF) или бэк (Puppeteer)?
2. **Многоатлетный режим** — этот этап или вторая фаза?
3. **AI-инсайты** — rule-based или LLM? Бюджет?
4. **План тренировок** — есть в системе или Compliance показывать заглушку?
5. **Тёмная тема** — сейчас или вторым этапом?
6. **Локализация** — только RU или сразу EN?
7. **Минимальная поддержка браузеров** — Chrome / Safari / Firefox / Edge?

---

**Хорошей разработки! 🚀**
