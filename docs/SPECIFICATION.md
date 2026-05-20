# ТЗ · Sportsmen Analytics — редизайн дашборда

> **Версия:** 1.2
> **Дата:** 28 апреля 2026
> **Автор:** Артём Хахулин (тренер, владелец продукта)
> **Целевая аудитория:** разработчик / команда фронтенда
> **Текущая стадия:** прототип v3 (Вариант A) согласован, готов к реализации

---

## История изменений

### v1.2 (28 апреля 2026) — текущая
- **Архитектура раскрытия KPI переработана** (см. §4.3) — Вариант A
- KPI остаются равной ширины (`1fr × 4`), не сжимаются при раскрытии
- Детализация выезжает **отдельной панелью на всю ширину Main**, под KPI
- График получает в ~2.5 раза больше места (~880px вместо ~350px)
- **Добавлены требования к графику**: видимая ось Y с делениями, сетка, корректные подписи дат
- **Уточнён расчёт CV** — игнорировать недели с 0 км (фикс «CV 138%»)
- Прототип обновлён до v3: `prototype/sportsmen_analytics_v3_variant_a.html`

### v1.1
- Фиксы карточки «Километров»
- Вкладки переведены в паттерн пилюль (как HR-зоны)
- Добавлена CV-логика с семантической раскраской (4 уровня)

### v1.0
- Первичная версия

---

## 1. Контекст и цель

### 1.1. Что есть сейчас
Веб-приложение Sportsmen Analytics — аналитический дашборд для тренеров и спортсменов на выносливость. Backend Turso, фронтенд отрисовывает графики из агрегированных данных (Garmin / Strava / TCX).

Сохраняемый функционал: KPI-блок, HR-зоны, distribution donut, weekly grid, LTHR-настройка, PMC, Recovery, фильтры, refresh.

### 1.2. Цель редизайна
1. Уровень индустрии (TrainingPeaks, Intervals.icu, Runalyze)
2. Освободить место упрощением настроек
3. Добавить hrTSS, поляризацию (Seiler), план vs факт
4. AI-инсайты — текстовые выводы из данных
5. **Детализация KPI с большим местом для графиков** (новое v1.2)

### 1.3. Что НЕ входит
Многоатлетный режим, новые устройства, редактирование тренировок, мобильная версия, тёмная тема.

---

## 2. Артефакты дизайна

- **`prototype/sportsmen_analytics_v3_variant_a.html`** — **актуальный** (Вариант A)
- `prototype/sportsmen_analytics_v2_fixed.html` — v2, для истории
- `prototype/sportsmen_analytics_interactive.html` — v1, для истории

При расхождениях — **прототип v3 имеет приоритет**.

---

## 3. Архитектура страницы

### 3.1. Layout

```
AppShell (макс. 1400px)
├── Sidebar (220px фиксированный)
└── Main Content (flex: 1)
```

### 3.2. Структура Main

| #  | Блок                                  | Статус       | Сетка             |
|----|---------------------------------------|--------------|-------------------|
| 1  | Header                                | НОВЫЙ        | row, full-width   |
| 2  | Meta-bar                              | НОВЫЙ        | row, full-width   |
| 3  | KPI-grid                              | ОБНОВИТЬ     | **4 равные**      |
| 4  | **Drilldown panel** (опционально)     | **НОВЫЙ v1.2** | full-width      |
| 5  | Recovery                              | СОХРАНИТЬ    | 3 колонки         |
| 6  | PMC                                   | СОХРАНИТЬ    | full-width        |
| 7  | HR-zones + Donut                      | ОБНОВИТЬ     | 1.5fr 1fr         |
| 8  | HR-zones by weeks                     | ОБНОВИТЬ     | 4 колонки         |
| 9  | AI-инсайты                            | НОВЫЙ        | full-width        |
| 10 | Power curve + Compliance              | НОВЫЙ        | 2 колонки         |

---

## 4. Компоненты — детально

### 4.1. Sidebar

**Файл:** `components/Sidebar/Sidebar.tsx`

Подкомпоненты: `UserHeader`, `AthleteSelect`, `PeriodFilter` (дефолт 14d), `ActivityPills`, `GroupingToggle` (синхронит с активной DrilldownPanel), `SyncStatusBlock`, `SessionInfoLink`.

---

### 4.2. Header + Meta-bar

```tsx
<div class="title-row">
  <Emoji icon="🏃" />
  <h1>Аналитика спортсмена · {athleteName}</h1>
  <Actions>
    <Button onClick={generatePdf}>📄 PDF-отчёт</Button>
    <IconButton onClick={openGlobalSettings}>⚙</IconButton>
  </Actions>
</div>
<MetaBar>
  {dateRangeLabel} · {activitiesCount} активностей · группировка: {grouping} · ✓ обновлено {sinceLastSync}
</MetaBar>
```

---

### 4.3. KPI Grid + DrilldownPanel — ★ ПЕРЕРАБОТАНО v1.2

> **ВНИМАНИЕ:** архитектура изменилась. Раскрытие происходит **не внутри карточки**, а **отдельной панелью под KPI**.

#### 4.3.1. Принцип

```
┌───────────┬───────────┬───────────┬───────────┐
│Тренировок │  Часов    │ Км [★]    │  hrTSS    │ ← KPI всегда 1fr × 4
└───────────┴───────────┴───────────┴───────────┘
                  ▼ (стрелка вниз от активной KPI)
┌─────────────────────────────────────────────────┐
│ Километров — детализация    [▾ свернуть]        │
│ [типы] [недели] [месяцы]                        │
│ 281    5:51/км    [CV 32%]                      │
│                                                 │
│ [график на всю ширину Main с осью Y]            │
│                                                 │
│ [инсайт]                                        │
│ [легенда + сводка]                              │
└─────────────────────────────────────────────────┘
```

**Главное преимущество:** графику доступна вся ширина Main (~945px), а не узкий слот в KPI-сетке.

#### 4.3.2. KpiCard — обновлено

```tsx
interface KpiCardProps {
  id: 'workouts' | 'hours' | 'distance' | 'hrtss';
  label: string;
  value: string | number;
  delta?: { value: string; direction: 'up' | 'down' } | null;
  warningBadge?: { text: string; severity: 'info' | 'warn' | 'bad' };
  sparkline?: number[];
  isExpandable: boolean;
  isActive: boolean;
  onClick: () => void;
}
```

**Состояния:**
- `default` — серый фон `#F5F4EF`
- `hover` — `#EAE8E0`
- `active` — белый фон + синяя рамка 1.5px `#185FA5` + **CSS-стрелка вниз**

**Стрелка вниз для активной KPI:**

```css
.kpi.active::after {
  content: '';
  position: absolute;
  bottom: -10px;
  left: 50%;
  transform: translateX(-50%);
  width: 0;
  height: 0;
  border-left: 8px solid transparent;
  border-right: 8px solid transparent;
  border-top: 10px solid #185FA5;
}
.kpi.active::before {
  /* Внутренний белый треугольник для эффекта стрелки */
  content: '';
  position: absolute;
  bottom: -7px;
  left: 50%;
  transform: translateX(-50%);
  width: 0;
  height: 0;
  border-left: 6px solid transparent;
  border-right: 6px solid transparent;
  border-top: 7px solid #FFFFFF;
}
```

**Поведение:**
- Клик по неактивной KPI → закрывает текущую панель + открывает новую
- Клик по активной KPI → закрывает панель
- Клик по «▾ свернуть» внутри → закрывает
- **Только одна панель открыта одновременно**

**Если есть `warningBadge`** — показывается **вместо** обычной дельты, чтобы предупреждение видно даже при свёрнутой панели.

#### 4.3.3. DrilldownPanel — НОВЫЙ компонент

**Файл:** `components/KpiGrid/DrilldownPanel/DrilldownPanel.tsx`

```tsx
interface DrilldownPanelProps {
  kpiId: 'workouts' | 'hours' | 'distance' | 'hrtss';
  isOpen: boolean;
  onClose: () => void;
  data: DrilldownData;
}
```

**Layout структура (header → stat row → tabs panes → footer):**

##### Header row
- **Слева:** заголовок «{KPI name} — детализация» + пилюли-вкладки
- **Справа:** ссылка `▾ свернуть`
- Бейдж сверху: `★ детализация · {KPI name}` (абсолютное позиционирование)

##### Tabs (пилюли, паттерн HR-зон)
- `типы` / `недели` / `месяцы` — пилюли в одной строке с заголовком
- Активная: `bg: #E6F1FB; color: #185FA5; font-weight: 500`
- Неактивная: `bg: #FFFFFF; border: 0.5px solid rgba(0,0,0,0.1)`

##### Stat row
- **Большое число** (24px, weight 500): главная метрика
- **Метаданные** (11px серый): средние, темп, частота
- **CV-плашка** (см. §4.3.5)

##### Chart pane — `weeks` / `months` — ★ КРИТИЧЕСКАЯ ЧАСТЬ v1.2

```
┌──────┬─────────────────────────────────────────┐
│ Y    │  Chart area                             │
│ axis │  ─ ─ ─ ─ ─ ─ ─ ─ ─ ─ ─ ─ ─ ─ ─ ─ ─ ─ ─ │ ← grid lines
│ 120  │  ─ ─ ─ ─ ─ ─ ─ ─ ─ ─ ─ ─ ─ ─ ─ ─ ─ ─ ─ │
│ 90   │  ─ ─ ─ ─ ─ ─ ─ ─ ─ ─ ─ ─ ─ ─ ─ ─ ─ ─ ─ │
│ 60   │  ▮      ▮▮▮▮▮  ▮▮▮▮▮                   │
│ 30   │  ▮▮     ▮▮▮▮▮▮▮▮▮▮▮▮▮                  │
│  0   │ ━▮▮━━━▮▮━▮▮▮▮▮▮▮━▮▮▮▮▮▮━━▮▮━━━━━━━━━━━ │ ← baseline
│      │   Mar 30  Apr 6  Apr 13  Apr 20  Apr 27│
└──────┴─────────────────────────────────────────┘
```

**Y axis (обязательно!):**
- 5 делений: `max`, `0.75 × max`, `0.5 × max`, `0.25 × max`, `0`
- Округление к удобному значению (max=101 → шкала до 120)
- Значения берутся с бэка (`distance.chartScale.ticks`)
- Шрифт 9px, цвет `#888780`, выравнивание по правому краю

**Grid lines:**
- 5 горизонтальных линий
- Цвет промежуточных: `rgba(0,0,0,0.08)`
- Цвет baseline (0): `rgba(0,0,0,0.2)`
- Толщина: 0.5px

**Bars:**
- Stacked bars (стэк по типам активности)
- Высота `value / maxValue × chartHeight`
- Над столбиком (top: -4px): значение в км (10px, weight 500)
- Под столбиком: подпись X из `weekStartLabel` (9px, серый)
- Hover: opacity 0.75
- Click: tooltip с деталями

**Размеры:**
- Высота `bars-row`: 130px
- Gap столбиков: 14px (weeks) / 60px (months)
- Max-width столбика: 80px (weeks) / 100px (months)

##### Tab "По типам"

```
🏃 Бег        ━━━━━━━━━━━━━━━━━━━━━━  252 км   89%
🚴 Велосипед  ━━━━                    29 км   11%
```

Полоски `width: percentage` от общей суммы. Под ними — inline-insight о структуре.

##### Inline insight (под графиком)

```html
<div class="dd-insight warn">
  <div class="dd-insight-icon">!</div>
  <span><b>Заметная нестабильность.</b> CV 32% в норме, но max/min — почти 7×.</span>
</div>
```

Логика см. §4.3.6.

##### Footer
- Легенда с разбивкой по типам и абсолютами: `🟢 Бег 252 км · 89%`
- Сводка справа: `min · avg · max`

#### 4.3.4. Карточки KPI для MVP

| KPI            | Drilldown в MVP |
|----------------|-----------------|
| Тренировок     | этап 2          |
| Часов          | этап 2          |
| **Километров** | **MVP**         |
| hrTSS / неделю | этап 2          |

Архитектура `DrilldownPanel` должна позволять добавлять другие KPI без переделки.

#### 4.3.5. CV-плашка — расчёт и логика

**Формула:**
```
CV = (stdDev / mean) × 100
```

**КРИТИЧЕСКИ ВАЖНО:**
- Считать **только по неделям с активностью** (`weeklyKm > 0`).
- ИЛИ считать по полным календарным неделям периода.
- **Не должен превышать 100%** при реальных данных.
- Если данных < 3 активных недель — НЕ показывать (`cv: null`).

**Семантическая раскраска:**

| CV       | Класс    | Цвета                              | Текст                          |
|----------|----------|------------------------------------|--------------------------------|
| < 20%    | `cv-good`| `bg: #EAF3DE`, `text: #3B6D11`    | `✓ CV {N}% · стабильно`        |
| 20–35%   | `cv-ok`  | `bg: #F1EFE8`, `text: #5F5E5A`    | `CV {N}% · нормально`          |
| 35–60%   | `cv-warn`| `bg: #FAEEDA`, `text: #854F0B`    | `⚠ CV {N}% · нестабильно`      |
| > 60%    | `cv-bad` | `bg: #FCEBEB`, `text: #A32D2D`    | `🔴 CV {N}% · хаотичный объём` |

#### 4.3.6. Inline-инсайты

| Условие                                | Severity | Текст                                                              |
|----------------------------------------|----------|--------------------------------------------------------------------|
| `CV > 60%`                             | bad      | «Высокая нестабильность. CV {N}% — хаотичный объём: {min}→{max} км. {context}» |
| `CV 35-60%`                            | warn     | «Заметная нестабильность. CV {N}% в норме, но max/min — почти {N}×. {context}» |
| `CV 20-35%`                            | info     | (необязательно, можно скрыть)                                      |
| `lastWeekKm < avgKm × 0.3`             | warn     | «Текущая неделя {N}км — резкое снижение от среднего {avg}км.»     |
| `monthGrowth > 50%`                    | warn     | «Резкий скачок: {prev}→{curr}. Нагрузка 10/10 — следите.»          |
| `monthDrop < -40%`                     | warn     | «Резкий спад в {month} ({pct}%). Травма/болезнь — корректируйте план.» |
| `singleTypeRatio > 90% && others`      | info     | «{Type} — основной вид ({N}%). Минимум кросс-тренинга.»            |

`context` — короткое описание текущей недели:
- «Текущая неделя 7км — пропуск/отдых/болезнь?»

**Один инсайт за раз** — берём с наивысшим приоритетом (bad > warn > info).

#### 4.3.7. Синхронизация с GroupingToggle

При смене группировки в сайдбаре — переключается активная вкладка:
- `Неделя` → `weeks`
- `Месяц` → `months`
- `Год` → `months` (12 месяцев) с сравнением vs предыдущий год

#### 4.3.8. Логика отсутствия дельты

Если `previousPeriodValue === null`:
- ❌ НЕ показывать прочерк `—`
- ✅ Просто не выводить блок дельты

---

### 4.4. Recovery (RHR / HRV / Сон)

3 карточки `RecoveryCard` в grid.

```tsx
interface RecoveryCardProps {
  metric: 'rhr' | 'hrv' | 'sleep';
  currentValue: number;
  unit: string;
  delta: { value: string; direction: 'up' | 'down' };
  series: TimeSeriesPoint[];
  normalRange?: { min: number; max: number };
  goalLine?: number;
  conclusion: { text: string; status: 'good' | 'warning' | 'bad' };
}
```

- **RHR**: график + опциональная полоса нормы
- **HRV**: график + **обязательная** полоса индивидуальной нормы
- **Sleep**: bars + **обязательная** пунктирная линия цели (8ч)

---

### 4.5. Training Load · PMC

**Цвета линий:**
- CTL = `#185FA5`
- ATL = `#D85A30`
- TSB = `#BA7517` пунктир

**Округление:** 1 знак (94.5, +16.4, −8.7).

**LTHR:** validation 80-220.

---

### 4.6. Time in HR-zones

- Над каждым столбиком: % крупно + ч мелко серым
- Пунктирная рамка = план, заливка = факт
- Tabs `5 зон / Seiler 80/20`
- Поляризация-плашка под чартом

---

### 4.7. Distribution Donut

Без изменений по логике, исправить обрезку легенды.

---

### 4.8. HR-zones by weeks

В каждой карточке: 5 баров + строка `9.7ч · 160км` снизу. Под сеткой — линия тренда CTL.

---

### 4.9. AI-инсайты

```tsx
interface Insight {
  type: 'success' | 'warning' | 'info';
  text: string;
  source: 'training_load' | 'recovery' | 'forecast' | 'compliance';
  priority: number;
}
```

| Условие                          | Тип      | Текст                                                |
|----------------------------------|----------|------------------------------------------------------|
| TSB > 10 && RHR ↓ && HRV ↑       | success  | «Все три индикатора зелёные. Время для ключевой.»   |
| TSB < -20                        | warning  | «TSB < -20. Заложите разгрузку.»                    |
| Avg sleep < goal - 0.5           | warning  | «Дефицит сна {N}ч от цели {M}ч.»                    |
| Прогноз гонки лучше PB           | success  | «Прогноз {distance}: {time} (PB {pb}).»             |

---

### 4.10. Power Curve

Линейный график best efforts: 5с / 1м / 5м / 20м / 60м.

---

### 4.11. Compliance

3 строки: Объём, Интенсивность (TSS), Ключевые тренировки.

```
volume = sum(actual_h) / sum(planned_h) × 100
tss = sum(actual_tss) / sum(planned_tss) × 100
key = count(actual_key) / count(planned_key)
```

---

## 5. Универсальный GearMenu

Универсальная шестерёнка для блоков. Открытие по клику, закрытие по клику вне или Esc. Только одно меню одновременно. Сохранение в localStorage.

---

## 6. Backend API

### 6.1. GET /api/dashboard/summary

**Ответ — секция distance:**

```typescript
{
  distance: {
    total: number;
    avgPace: { run: string; bike: string; swim: string };
    avgPerWeek: number;
    cv: number | null;                      // null если < 3 активных недель
    cvSeverity: 'good' | 'ok' | 'warn' | 'bad' | null;
    deltaPct: number | null;                // null если нет данных для сравнения
    
    byType: { run: number; bike: number; swim: number };
    
    byWeek: Array<{
      weekStart: string;                    // ISO дата
      weekStartLabel: string;               // "Mar 30" — готовая подпись
      total: number;
      byType: { run: number; bike: number; swim: number };
    }>;
    
    byMonth: Array<{
      month: string;                        // "2026-04"
      monthLabel: string;                   // "Апрель"
      total: number;
      byType: { run: number; bike: number; swim: number };
      deltaPct: number | null;
    }>;
    
    insight: {
      severity: 'good' | 'info' | 'warn' | 'bad';
      text: string;
    } | null;
    
    minWeekKm: number;
    maxWeekKm: number;
    
    // Для оси Y графика — ★ NEW v1.2
    chartScale: {
      min: number;                          // обычно 0
      max: number;                          // округлённое (101 → 120)
      ticks: number[];                      // [0, 30, 60, 90, 120]
    };
  }
}
```

**ВАЖНО:**
- `weekStartLabel` — готовый с бэка, фронт не парсит даты
- `cv` — только по активным неделям (исключая 0-км) ИЛИ по полным неделям
- `chartScale.ticks` — фронт рендерит как есть

### 6.2-6.7

`PATCH /api/athlete/{id}/lthr`, `POST /api/dashboard/refresh`, `GET /api/dashboard/insights`, `POST /api/dashboard/pdf`, `GET /api/athletes`, WebSocket `/ws/dashboard`.

---

## 7. Модели данных

```typescript
export type Sport = 'run' | 'bike' | 'swim' | 'strength' | 'other';
export type Period = '7d' | '14d' | '30d' | '90d' | '365d' | 'custom';
export type Grouping = 'week' | 'month' | 'year';
export type CvSeverity = 'good' | 'ok' | 'warn' | 'bad';
export type KpiId = 'workouts' | 'hours' | 'distance' | 'hrtss';

export interface DistanceWeekly {
  weekStart: string;
  weekStartLabel: string;
  total: number;
  byType: Record<Sport, number>;
}

export interface DistanceInsight {
  severity: 'good' | 'info' | 'warn' | 'bad';
  text: string;
}

export interface ChartScale {
  min: number;
  max: number;
  ticks: number[];
}
```

---

## 8. State management

```typescript
interface DashboardStore {
  // Filters
  selectedAthleteId: string;
  period: Period;
  activeSports: Sport[];
  grouping: Grouping;
  
  // UI state — ★ ОБНОВЛЕНО v1.2
  activeKpiDrilldown: KpiId | null;
  drilldownActiveTab: 'types' | 'weeks' | 'months';
  blockSettings: Record<string, BlockSettings>;
  
  // Data
  summary: DashboardSummary | null;
  isLoading: boolean;
  
  // Actions
  setPeriod: (period: Period) => void;
  setGrouping: (g: Grouping) => void;
  toggleKpiDrilldown: (kpi: KpiId) => void;     // ★ NEW v1.2
  closeDrilldown: () => void;                    // ★ NEW v1.2
  setDrilldownTab: (tab: string) => void;
}
```

**Логика toggleKpiDrilldown:**

```typescript
toggleKpiDrilldown: (kpi) => {
  const current = get().activeKpiDrilldown;
  if (current === kpi) set({ activeKpiDrilldown: null });
  else set({ activeKpiDrilldown: kpi });
}
```

**Синхронизация GroupingToggle ↔ DrilldownTab:**

```typescript
setGrouping: (g) => {
  set({ grouping: g });
  if (g === 'week') set({ drilldownActiveTab: 'weeks' });
  else if (g === 'month') set({ drilldownActiveTab: 'months' });
}
```

---

## 9. Технологический стек

React 18 + TypeScript, Vite, CSS Modules или Tailwind, Recharts + D3, Zustand, Tanstack Query, date-fns, Lucide React, Vitest + RTL.

---

## 10. Файловая структура

```
src/
├── components/
│   ├── Sidebar/
│   ├── Header/
│   ├── KpiGrid/
│   │   ├── KpiGrid.tsx
│   │   ├── KpiCard.tsx
│   │   ├── DrilldownPanel/             ★ NEW v1.2
│   │   │   ├── DrilldownPanel.tsx      ★ универсальный wrapper
│   │   │   ├── DistanceDrilldown.tsx   ★ для «Километров»
│   │   │   ├── DrilldownChart.tsx      ★ chart с осью Y и сеткой
│   │   │   ├── ByTypesPane.tsx
│   │   │   ├── ByWeeksPane.tsx
│   │   │   └── ByMonthsPane.tsx
│   │   ├── CvBadge.tsx
│   │   └── DistanceInsight.tsx
│   ├── Recovery/
│   ├── TrainingLoad/
│   ├── HrZones/
│   ├── Insights/
│   ├── PowerCurve/
│   ├── Compliance/
│   └── Common/
│       ├── Block.tsx
│       ├── GearMenu.tsx
│       ├── Sparkline.tsx
│       ├── Toast.tsx
│       └── Modal.tsx
├── hooks/
├── store/
├── api/
├── types/
└── utils/
    ├── formatters.ts
    ├── calc.ts (CV, polarization)
    └── chartScale.ts                   ★ NEW v1.2
```

---

## 11. Дизайн-токены

```css
:root {
  /* Sport colors */
  --color-run: #97C459;
  --color-bike: #378ADD;
  --color-swim: #1D9E75;
  
  /* HR zones */
  --color-z1: #C0DD97;
  --color-z2: #97C459;
  --color-z3: #EF9F27;
  --color-z4: #BA7517;
  --color-z5: #E24B4A;
  
  /* Semantic */
  --color-success: #3B6D11;
  --color-success-bg: #EAF3DE;
  --color-warning: #854F0B;
  --color-warning-bg: #FAEEDA;
  --color-danger: #A32D2D;
  --color-danger-bg: #FCEBEB;
  --color-info: #185FA5;
  --color-info-bg: #E6F1FB;
  
  /* Neutral */
  --color-text-primary: #2C2C2A;
  --color-text-secondary: #5F5E5A;
  --color-text-tertiary: #888780;
  --color-bg-primary: #FFFFFF;
  --color-bg-secondary: #F5F4EF;
  --color-border: rgba(0, 0, 0, 0.15);
  
  /* Typography */
  --font-sans: -apple-system, BlinkMacSystemFont, 'Segoe UI', sans-serif;
  --font-size-xs: 10px;
  --font-size-sm: 11px;
  --font-size-md: 13px;
  --font-size-xl: 18px;
  --font-size-2xl: 24px;
  
  /* Transitions */
  --transition-fast: 0.15s;
  --transition-normal: 0.3s;
}
```

---

## 12. План разработки

### Спринт 1 — Каркас (1 неделя)
- [ ] Vite + React + TypeScript + ESLint/Prettier
- [ ] tokens.css
- [ ] AppShell
- [ ] Общие компоненты: Block, Toast, Modal, GearMenu, Sparkline
- [ ] Zustand + Tanstack Query

### Спринт 2 — Sidebar (3-4 дня)
- [ ] UserHeader, AthleteSelect
- [ ] PeriodFilter с custom-range
- [ ] ActivityPills
- [ ] GroupingToggle
- [ ] SyncStatusBlock

### Спринт 3 — KPI Grid + Drilldown (1 неделя) ★ ОБНОВЛЕНО v1.2
- [ ] KpiGrid с равной шириной 1fr × 4
- [ ] KpiCard с состояниями default/hover/active
- [ ] **CSS-стрелка вниз** для активной KPI
- [ ] **DrilldownPanel** универсальный компонент
- [ ] **Анимация slideDown 0.3s**
- [ ] **DistanceDrilldown** для «Километров»
- [ ] **DrilldownChart** с осью Y, сеткой, подписями дат
- [ ] ByTypesPane, ByWeeksPane, ByMonthsPane
- [ ] **CvBadge** с 4 уровнями
- [ ] **DistanceInsight** с правилами
- [ ] toggleDrilldown / closeDrilldown
- [ ] Синхронизация активной вкладки с GroupingToggle
- [ ] **Тесты:** переключение, расчёт CV без пустых недель

### Спринт 4 — Recovery, PMC, Zones (1 неделя)
- [ ] RecoveryBlock с 3 RecoveryCard
- [ ] Полоса нормы для RHR/HRV
- [ ] Линия цели для Sleep
- [ ] PmcBlock с правильными цветами
- [ ] LthrControl
- [ ] HrZonesBars с план/факт
- [ ] HrZonesDonut

### Спринт 5 — Weekly + Insights + Bottom row (1 неделя)
- [ ] WeeklyZonesGrid с метаданными
- [ ] Линия тренда CTL
- [ ] AiInsights
- [ ] PowerCurve
- [ ] ComplianceBlock
- [ ] PDF-генерация

### Спринт 6 — Полировка (3-5 дней)
- [ ] Адаптив
- [ ] Loading / error / empty states
- [ ] Локализация
- [ ] localStorage для настроек
- [ ] Lighthouse audit

---

## 13. Acceptance Criteria

### 13.1. Общие
- ✅ 1280×800, 1440×900, 1920×1080 — без переполнений
- ✅ Все интерактивные имеют hover
- ✅ Все числа округлены
- ✅ Lighthouse ≥ 85, A11y ≥ 90

### 13.2. KPI Grid + DrilldownPanel — v1.2 ★
- ✅ KPI всегда **равной ширины** (`grid-template-columns: 1fr 1fr 1fr 1fr`)
- ✅ KPI **не сжимаются** при раскрытии детализации
- ✅ Активная KPI имеет **синюю рамку 1.5px** + **CSS-стрелку вниз**
- ✅ DrilldownPanel **на всю ширину Main**
- ✅ Анимация открытия `slideDown 0.3s`
- ✅ Только одна панель открыта одновременно
- ✅ Закрытие через `▾ свернуть` или повторный клик по KPI
- ✅ Вкладки реализованы как **пилюли** в одной строке с заголовком
- ✅ 3 пилюли: `типы / недели / месяцы` (без эмодзи 📊 📅 🗓)
- ✅ Группировка в сайдбаре переключает пилюлю автоматически
- ✅ **График имеет видимую ось Y** с делениями 0/25/50/75/100% от max
- ✅ **Grid lines** на каждом делении Y
- ✅ **Подписи X** — даты в формате `Mar 30` (баг «Спорт» исправлен)
- ✅ **CV-плашка** с правильной семантикой (4 уровня)
- ✅ **CV рассчитывается без пустых недель** (фикс «CV 138%»)
- ✅ **При отсутствии дельты** прочерк `—` НЕ показывается
- ✅ **Силовая** не показывается в разбивке (нет км)
- ✅ **«Прочее»** не появляется в легенде
- ✅ **Inline-инсайт** генерируется по правилам §4.3.6

### 13.3. PMC
- ✅ CTL = `#185FA5`, ATL = `#D85A30`, TSB = `#BA7517` пунктир
- ✅ Числа округлены до 1 знака
- ✅ LTHR валидируется (80-220)

### 13.4. Зоны
- ✅ Над столбиком два значения: % крупно + ч мелко серым
- ✅ Пунктирная рамка = план, заливка = факт
- ✅ Поляризация Seiler

### 13.5. Recovery
- ✅ HRV график имеет полосу нормы
- ✅ Sleep имеет линию цели 8ч

### 13.6. Шестерёнка
- ✅ В каждом блоке есть ⚙
- ✅ Меню открывается/закрывается корректно
- ✅ Только одно меню открыто одновременно
- ✅ Настройки сохраняются в localStorage

---

## 14. Тест-данные

В `src/mocks/`: `athletes.json`, `activities.json`, `recovery.json`, `plans.json`. Использовать **MSW** для интерцепта API.

---

## 15. Деплой

| Окружение | Backend             | URL                                |
|-----------|---------------------|------------------------------------|
| Local     | localhost + MSW     | localhost:5173                     |
| Staging   | api-staging.app     | staging.sportsmen-analytics.app    |
| Prod      | api.app             | sportsmen-analytics.app            |

---

## 16. Открытые вопросы

1. **PDF-генерация** — фронт (jsPDF) или бэк (Puppeteer)?
2. **Многоатлетный режим** — этот этап или вторая фаза?
3. **AI-инсайты** — rule-based или LLM? Бюджет?
4. **План тренировок** — есть в системе или Compliance показывать заглушку?
5. **Темная тема** — сейчас или второй этап?
6. **Локализация** — только русский или сразу с EN?
7. **Минимальная поддержка браузеров** — Chrome / Safari / Firefox?

---

## 17. Контакты

- **Владелец продукта:** Артём Хахулин
- **Прототип v3 (актуальный):** `prototype/sportsmen_analytics_v3_variant_a.html`
- **Прототип v2:** `prototype/sportsmen_analytics_v2_fixed.html` (history)
- **Прототип v1:** `prototype/sportsmen_analytics_interactive.html` (history)

---

## 18. Чек-лист багфиксов из реализации

### 18.1. Карточка «Километров» — критические фиксы

- [ ] **Bug:** «Спорт» появляется как категория на оси X
  - **Fix:** проверить data layer, фильтровать неизвестные категории
  - **Test:** в подписях X нет ничего кроме дат

- [ ] **Bug:** CV > 100% (было 138%)
  - **Fix:** считать CV только по неделям с активностью (km > 0). Альтернатива: только по полным неделям периода
  - **Test:** для реальных данных CV всегда < 100%

- [ ] **Bug:** «Прочее» в легенде
  - **Fix:** проверить data layer на источник (`walking` / `manual_entry` / `other`). Переименовать или скрывать если 0 км
  - **Test:** в легенде нет неопознанных типов

- [ ] **Bug:** прочерк `—` появляется когда нет дельты
  - **Fix:** если `delta === null` — пропускать вывод
  - **Test:** период 7 дней → прочерк не показывается

- [ ] **Bug:** график обрезан по оси X (значения прижаты вправо)
  - **Fix:** padding chart-area: `0 8px`, столбики `flex: 1` равномерно
  - **Test:** все столбики на равном расстоянии, первый не у края

- [ ] **Bug:** нет оси Y и сетки — нельзя оценить масштаб
  - **Fix:** реализовать `DrilldownChart` с обязательной осью Y и grid-lines (см. §4.3.3)
  - **Test:** видны 5 делений Y

### 18.2. Архитектурные изменения v1.2

- [ ] **Migration:** карточка «Километров» больше не раскрывается **внутри** KPI-сетки
  - **Fix:** реализовать `DrilldownPanel` как отдельный компонент **под** KPI-сеткой
  - **Test:** при раскрытии KPI остаются равной ширины, панель появляется ниже

- [ ] **Add:** CSS-стрелка вниз у активной KPI
  - **Test:** визуально связь KPI → панель очевидна

- [ ] **Add:** анимация `slideDown 0.3s` при открытии панели

### 18.3. Inline-инсайт

- [ ] **Add:** под графиком плашка с выводом
  - **Fix:** реализовать `DistanceInsight` (см. §4.3.6)
  - **Test:** для CV > 60% — красная плашка с описанием

### 18.4. Свёрнутая карточка

- [ ] **Add:** в свёрнутом виде, если CV ≥ 35%, показывать `⚠ CV {N}%` вместо обычной дельты
  - **Test:** свернуть панель → видна предупреждающая плашка

---

**Конец ТЗ. Версия 1.2.**

> Дополнения и изменения вносить через Pull Request к этому файлу.
