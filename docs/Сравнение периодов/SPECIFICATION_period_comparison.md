# Спецификация: Сравнение периодов

> **Версия:** 1.0
> **Дата:** 29 апреля 2026
> **Статус:** прототип согласован, готов к реализации
> **Прототип:** `prototype/period_comparison_simple.html`
> **Связь с основным ТЗ:** дополнение к §19 SPECIFICATION.md v1.3

---

## 1. Концепция

Тренер должен иметь возможность **сравнить любые два периода** активности атлета по объёму (часы) и расстоянию (км), с гибким контролем учитываемых видов спорта.

**Базовый сценарий:**
> «Хочу понять, как мой подопечный тренировался последние 14 дней по сравнению с предыдущими 14 днями.»

**Расширенный сценарий:**
> «Хочу сравнить апрель 2026 с апрелем 2025, но только по бегу и силовой — потому что в 2025 ещё была игровая активность, которой нет в этом году.»

---

## 2. UX-решение

Минималистичный интерфейс с двумя главными контролами:

```
┌─────────────────────────────────────────────────────────┐
│ Период 1 [───────────]          Период 2 [───────────]  │
│ • даты + быстрые шаблоны        • даты + быстрые шаблоны│
└─────────────────────────────────────────────────────────┘
┌─────────────────────────────────────────────────────────┐
│ Активности: [● Все] [○ Выбрать]                         │
│ 🏃 🚴 🏊 ⛷ 💪 🏃‍♂️ 🚴‍♀️ ⛹️                                  │
└─────────────────────────────────────────────────────────┘
┌──────────────────────┬──────────────────────────────────┐
│ Период 1             │ Период 2                         │
│ Карточка с разбивкой │ Карточка с разбивкой             │
└──────────────────────┴──────────────────────────────────┘
┌─────────────────────────────────────────────────────────┐
│ 📊 Результат сравнения                                  │
│ Часы / Километры / Дельта                               │
│ Inline-инсайт                                           │
└─────────────────────────────────────────────────────────┘
```

---

## 3. Компоненты — детальное описание

### 3.1. PeriodInputBlock

Блок ввода одного периода. Используется дважды на странице — для Период 1 и Период 2.

**Файл:** `components/PeriodComparison/PeriodInputBlock.tsx`

```tsx
interface PeriodInputBlockProps {
  label: string;                    // "Период 1 · Основной"
  variant: 'current' | 'compare';   // Влияет на цвет рамки и точки
  startDate: string;                // ISO date "2026-04-14"
  endDate: string;                  // ISO date "2026-04-27"
  onDateChange: (start: string, end: string) => void;
  presets: Array<{                  // Быстрые шаблоны под полем
    label: string;
    type: 'days_back' | 'current_month' | 'previous_period' | 'year_ago' | 'previous_month';
    days?: number;                  // Для типа days_back
  }>;
  meta: {                           // Динамическая мета снизу
    days: number;
    activitiesCount: number;
  };
}
```

**Визуал:**
- Padding 12px, фон `#F5F4EF`
- Border-left 3px:
  - `current` → `#185FA5`
  - `compare` → `#888780`
- Заголовок 10px, серый, uppercase
- Цветная точка-индикатор слева от заголовка
- Два `<input type="date">` с разделителем `→`
- Под датами — пилюли быстрых шаблонов (12px, прозрачный фон)
- Снизу мета: `14 дней · 28 активностей`

**Шаблоны быстрого выбора (per-period):**

| Период 1 | Период 2 |
|----------|----------|
| последние 7 дней | предыдущий равный |
| последние 14 дней | год назад |
| последние 30 дней | прошлый месяц |
| текущий месяц | |

**Логика шаблонов:**
- `days_back: 7` → конец = сегодня, начало = сегодня - 6 дней
- `current_month` → начало = первое число текущего месяца, конец = последнее число
- `previous_period` (только для Период 2) → длина = длина Период 1, конец = Период 1 start - 1
- `year_ago` (только для Период 2) → даты Период 1 - 1 год
- `previous_month` (только для Период 2) → начало/конец прошлого календарного месяца

### 3.2. ActivityFilterBlock

Блок выбора учитываемых видов спорта.

**Файл:** `components/PeriodComparison/ActivityFilterBlock.tsx`

```tsx
interface ActivityFilterBlockProps {
  mode: 'all' | 'custom';
  selectedSports: Set<Sport>;
  availableSports: Sport[];          // Виды, которые есть хотя бы в одном периоде
  onModeChange: (mode: 'all' | 'custom') => void;
  onSportToggle: (sport: Sport) => void;
  onSelectAll: () => void;
  onDeselectAll: () => void;
}
```

**Структура:**
1. Заголовок «Активности» + segment-control `Все активности / Выбрать`
2. Ряд пилюль с видами спорта + кнопки `все / снять все`
3. Сводка снизу с описанием текущего фильтра

**Поведение:**
- Режим `all` (default):
  - Учитываются **все виды активности** из обоих периодов
  - Пилюли с видами визуально приглушены (`opacity: 0.5`) — намёк, что они не управляют фильтром
  - Сводка: «✓ Учитываются **все активности**»
  
- Режим `custom`:
  - Учитываются только виды с `selectedSports`
  - Клик по пилюле — toggle on/off
  - Кнопка «все» — добавляет всё в `selectedSports`
  - Кнопка «снять все» — очищает `selectedSports`
  - Сводка: «✓ Выбрано **N**: 🏃 Бег, 💪 Силовая, …»
  - Если selectedSports пустое — сводка с предупреждением: «⚠ Не выбрано ни одной активности»

- **Авто-переключение** при клике по пилюле в режиме `all`:
  - Режим переключается в `custom`
  - Кликнутая пилюля **остаётся выбранной**, остальные — тоже **остаются выбранными**
  - Это предотвращает неожиданное обнуление

### 3.3. PeriodComparisonCard

Карточка с разбивкой одного периода по видам спорта.

**Файл:** `components/PeriodComparison/PeriodComparisonCard.tsx`

```tsx
interface PeriodComparisonCardProps {
  variant: 'current' | 'compare';
  label: string;                    // "Период 1 · Основной"
  periodLabel: string;              // "14 апр – 27 апр 2026"
  daysCount: number;                // 14
  sports: Array<{
    key: Sport;
    icon: string;
    name: string;
    hours: number;
    km: number | null;
    excluded: boolean;              // true если вид не учитывается из-за фильтра
  }>;
}
```

**Визуал:**
- Border-left 3px (current = синий, compare = серый)
- Padding 16px
- Заголовок (10px, uppercase, серый) + точка-индикатор
- Ниже — формат периода (15px, weight 500)
- Под ним — мета (`14 дней`)
- Список видов спорта построчно: `[icon] [name] [hours] [km]`
- Исключённые виды — `opacity: 0.35` + `text-decoration: line-through`
- Внизу — итоговая строка с фоном `#F5F4EF`: «Итого: X.X ч · YY км»

### 3.4. ResultCard

Сводный результат сравнения с дельтой и инсайтом.

**Файл:** `components/PeriodComparison/ResultCard.tsx`

```tsx
interface ResultCardProps {
  period1: {
    label: string;                  // "14 апр – 27 апр 2026"
    sportsCount: number;
    totalHours: number;
    totalKm: number;
  };
  period2: {
    label: string;
    sportsCount: number;
    totalHours: number;
    totalKm: number;
  };
  insight: {
    type: 'info' | 'warn';
    text: string;
  } | null;
}
```

**Структура:**
1. Заголовок «📊 Результат сравнения»
2. Таблица 4 колонки: `Метрика | Период 1 | Период 2 | Разница`
3. Строки таблицы:
   - Учтено видов спорта
   - Часов
   - Километров
4. Inline-инсайт (если есть)

**Расчёт дельты:**

```typescript
function computeDelta(value1: number, value2: number): {
  abs: number;
  pct: number;
  direction: 'up' | 'down' | 'flat';
} {
  const abs = value1 - value2;
  const pct = value2 > 0 ? (abs / value2) * 100 : 0;
  let direction: 'up' | 'down' | 'flat';
  if (Math.abs(pct) < 5) direction = 'flat';
  else direction = abs > 0 ? 'up' : 'down';
  return { abs, pct, direction };
}
```

**Цветовая семантика дельты:**
- `flat` (`|pct| < 5%`) → серая плашка `#F1EFE8` / `#5F5E5A`
- `up` → зелёная `#EAF3DE` / `#3B6D11`
- `down` → красная `#FCEBEB` / `#A32D2D`

**ВАЖНО:** для метрик «больше = лучше» (часы, км) логика прямая. Для метрик «меньше = лучше» (RHR, утомление) — инверсия. В рамках этой функции учитываются только часы и километры, поэтому проблем нет.

---

## 4. Логика inline-инсайтов

Под таблицей результата генерируется **один** инсайт по правилам:

### 4.1. Режим `all`

```typescript
function generateInsightForAllMode(period1, period2): Insight | null {
  const onlyIn1 = period1.sports.filter(s => !period2.sports.find(x => x.key === s.key));
  const onlyIn2 = period2.sports.filter(s => !period1.sports.find(x => x.key === s.key));
  
  if (onlyIn1.length === 0 && onlyIn2.length === 0) {
    return {
      type: 'info',
      text: 'Все виды активности присутствуют в обоих периодах. Сравнение полностью корректно.'
    };
  }
  
  return {
    type: 'warn',
    text: `Внимание: в периодах есть виды спорта, которые присутствуют только в одном из них. Это влияет на сравнение часов и километров. ${formatList(onlyIn1, onlyIn2)} Если нужно «честное» сравнение — выберите режим «Выбрать» и укажите общие виды.`
  };
}
```

### 4.2. Режим `custom`

```typescript
function generateInsightForCustomMode(selectedSports): Insight | null {
  if (selectedSports.size === 0) return null; // Empty state shows separately
  
  return {
    type: 'info',
    text: `Сравниваются только выбранные виды активности: ${formatSelectedList(selectedSports)}.`
  };
}
```

### 4.3. Empty state

Если в обоих периодах после фильтрации не осталось ни одного вида:

```html
<div class="empty-state">
  ⚠️ Не выбрано ни одной активности.
  Выберите хотя бы один вид спорта выше.
</div>
```

---

## 5. State management

### 5.1. Расширение DashboardStore

```typescript
// types.ts — расширение существующих типов
export type FilterMode = 'all' | 'custom';

// store/comparisonStore.ts — отдельный slice
interface ComparisonStore {
  isComparisonMode: boolean;          // Включён ли режим сравнения
  
  period1: {
    start: string;                     // ISO date
    end: string;
  };
  period2: {
    start: string;
    end: string;
  };
  
  filterMode: FilterMode;             // 'all' | 'custom'
  selectedSports: Set<Sport>;
  
  // Computed
  period1Data: PeriodData | null;
  period2Data: PeriodData | null;
  
  // Actions
  toggleComparisonMode: () => void;
  setPeriod1: (start: string, end: string) => void;
  setPeriod2: (start: string, end: string) => void;
  setFilterMode: (mode: FilterMode) => void;
  toggleSport: (sport: Sport) => void;
  selectAllSports: () => void;
  deselectAllSports: () => void;
  applyPreset: (
    period: 1 | 2, 
    type: 'days_back' | 'current_month' | 'previous_period' | 'year_ago' | 'previous_month',
    options?: { days?: number }
  ) => void;
}
```

### 5.2. Логика toggleSport с авто-переключением

```typescript
toggleSport: (sport: Sport) => {
  set(state => {
    // Если в режиме 'all' — переключаемся в 'custom' с сохранением всех текущих видов
    if (state.filterMode === 'all') {
      const allAvailable = getAllAvailableSports(state.period1Data, state.period2Data);
      // selectedSports должен содержать все, кроме того, на который кликнули
      const newSelected = new Set(allAvailable);
      newSelected.delete(sport);
      return { filterMode: 'custom', selectedSports: newSelected };
    }
    
    // Обычный toggle в режиме custom
    const newSelected = new Set(state.selectedSports);
    if (newSelected.has(sport)) newSelected.delete(sport);
    else newSelected.add(sport);
    return { selectedSports: newSelected };
  });
}
```

---

## 6. API расширение

### 6.1. Новый эндпоинт: GET /api/dashboard/comparison

```typescript
GET /api/dashboard/comparison?
  athlete_id=akhakhulin&
  
  // Период 1
  period1_start=2026-04-14&
  period1_end=2026-04-27&
  
  // Период 2
  period2_start=2026-03-31&
  period2_end=2026-04-13&
  
  // Фильтр: либо all, либо список через запятую
  activity_filter_mode=all                              // или 'custom'
  activity_types=run,bike,strength                      // только если mode=custom
```

### 6.2. Структура ответа

```typescript
interface ComparisonResponse {
  period1: PeriodComparisonData;
  period2: PeriodComparisonData;
  
  // Только если в одном из периодов есть виды, которых нет в другом
  // (помогает фронту не пересчитывать самому)
  asymmetry: {
    onlyInPeriod1: Sport[];          // ['ski']
    onlyInPeriod2: Sport[];          // ['ball_sport']
  } | null;
  
  // Общие виды (есть в обоих периодах)
  commonSports: Sport[];             // ['run', 'bike', 'strength']
}

interface PeriodComparisonData {
  period: {
    start: string;                   // "2026-04-14"
    end: string;                     // "2026-04-27"
    daysCount: number;               // 14
    activitiesCount: number;         // 32
  };
  
  // Все виды спорта в этом периоде
  // excluded зависит от фильтра — выставляется на бэке
  sports: Array<{
    key: Sport;
    name: string;                    // Локализованное имя
    icon: string;                    // Эмодзи или код иконки
    hours: number;                   // 26.2
    km: number | null;               // 220.5 или null если не применимо
    activitiesCount: number;         // 18
    excluded: boolean;               // true если фильтр исключил
  }>;
  
  // Итоги (только по неисключённым)
  totals: {
    hours: number;
    km: number;
    sportsCount: number;             // Кол-во неисключённых видов
  };
}
```

### 6.3. Логика бэка

```python
def compute_comparison(
    athlete_id: str,
    period1_start: date, period1_end: date,
    period2_start: date, period2_end: date,
    filter_mode: Literal['all', 'custom'],
    activity_types: list[str] | None,
) -> ComparisonResponse:
    
    # 1. Получить активности обоих периодов
    p1_activities = fetch_activities(athlete_id, period1_start, period1_end)
    p2_activities = fetch_activities(athlete_id, period2_start, period2_end)
    
    # 2. Сгруппировать по видам спорта
    p1_grouped = group_by_sport(p1_activities)
    p2_grouped = group_by_sport(p2_activities)
    
    # 3. Применить фильтр для расчёта excluded
    if filter_mode == 'all':
        # Все виды учитываются
        excluded_sports = set()
    else:
        # Только те, что в activity_types
        all_sports = set(p1_grouped.keys()) | set(p2_grouped.keys())
        excluded_sports = all_sports - set(activity_types)
    
    # 4. Подсчитать итоги
    p1_data = build_period_data(p1_grouped, excluded_sports)
    p2_data = build_period_data(p2_grouped, excluded_sports)
    
    # 5. Найти асимметрию
    p1_keys = set(p1_grouped.keys())
    p2_keys = set(p2_grouped.keys())
    only_in_p1 = list(p1_keys - p2_keys)
    only_in_p2 = list(p2_keys - p1_keys)
    
    asymmetry = None
    if only_in_p1 or only_in_p2:
        asymmetry = {
            'onlyInPeriod1': only_in_p1,
            'onlyInPeriod2': only_in_p2,
        }
    
    return {
        'period1': p1_data,
        'period2': p2_data,
        'asymmetry': asymmetry,
        'commonSports': list(p1_keys & p2_keys),
    }
```

---

## 7. Размещение в дашборде

### 7.1. Где живёт функция

**Вариант A — отдельная страница** (рекомендую):
- В навигации добавляется новый пункт «Сравнение периодов» (`/comparison`)
- Открывается отдельная страница с `period_comparison_simple.html` структурой
- На главном дашборде остаётся **простая дельта** с предыдущим периодом (как было)
- Ссылка с главной: «Подробное сравнение →» открывает `/comparison`

**Вариант B — модальное окно**:
- Кнопка «🔬 Сравнить периоды» в шапке дашборда
- Открывает полноэкранный модал с тем же интерфейсом

**Я рекомендую Вариант A**, потому что:
- Сравнение периодов — это focused-задача, требующая концентрации
- Удобнее ссылаться по URL (`/comparison?p1_start=...&p1_end=...`)
- Лучше для печати / экспорта в PDF
- Не перекрывает основной дашборд

### 7.2. URL-параметры (для shareable links)

```
/comparison?
  p1_start=2026-04-14&p1_end=2026-04-27&
  p2_start=2026-03-31&p2_end=2026-04-13&
  filter=all
```

или

```
/comparison?
  p1_start=2026-04-14&p1_end=2026-04-27&
  p2_start=2026-03-31&p2_end=2026-04-13&
  filter=custom&types=run,strength
```

Это позволит тренеру шарить ссылку на конкретное сравнение коллегам или сохранять закладки.

---

## 8. Адаптивность

### 8.1. Desktop (≥ 1025px)
- Контролы (период 1 + период 2) — `grid-template-columns: 1fr 1fr`
- Карточки результата — `grid-template-columns: 1fr 1fr`

### 8.2. Tablet (641-1024px)
- Контролы остаются `1fr 1fr`
- Карточки результата остаются `1fr 1fr`
- Date-инпуты могут переноситься — flex-wrap

### 8.3. Mobile (≤ 640px)
- Контролы становятся `grid-template-columns: 1fr` (вертикально)
- Карточки результата `grid-template-columns: 1fr`
- Пилюли активностей в одну строку с горизонтальным скроллом
- Кнопки `все / снять все` тоже в этой строке

```css
@media (max-width: 640px) {
  .controls-row,
  .cmp-grid {
    grid-template-columns: 1fr;
  }
  .sport-pills {
    overflow-x: auto;
    flex-wrap: nowrap;
    padding-bottom: 4px;
  }
}
```

### 8.4. Date-input на мобильном
Использовать нативный `<input type="date">` — он автоматически открывает встроенный date-picker системы (iOS, Android).

---

## 9. Edge cases и обработка ошибок

### 9.1. Невалидные даты
- `period1_end < period1_start` → подсветить инпут красным, показать тултип «Дата конца не может быть раньше начала»
- `period1_start` в будущем → подсветить, тултип «Период не может быть в будущем»
- Период длиной > 365 дней → warning toast «Длинные периоды могут загружаться дольше»

### 9.2. Пересекающиеся периоды
- Если периоды частично пересекаются → нативный warning toast: «Периоды пересекаются на N дней. Это может искажать дельту.»
- Не блокирует, тренер сам решает

### 9.3. Нет данных в одном из периодов
- Карточка показывает «Нет активностей в этом периоде»
- Сравнение всё равно строится (один период с нулём), но дельта помечается как «100% потеря»

### 9.4. Empty state фильтра
- В режиме `custom` нет выбранных видов → не отрисовывать таблицу результата, показать message «Выберите хотя бы один вид спорта»

### 9.5. Все виды исключены
- В обоих периодах после фильтрации ноль видов → empty state

---

## 10. Acceptance Criteria

### 10.1. Базовая функциональность
- ✅ Можно ввести любые две даты для каждого периода
- ✅ Шаблоны быстрого выбора работают корректно (7д / 14д / 30д / месяц / предыдущий равный / год назад)
- ✅ Расчёт пересчитывается мгновенно при любом изменении (date / sport / mode)
- ✅ Дельта показывает абсолютное значение, процент и стрелку направления
- ✅ Цветовая семантика дельты соблюдается (зелёный +, красный -, серый ≈)

### 10.2. Фильтр активностей
- ✅ Дефолт — режим `Все активности`
- ✅ В режиме `Все` пилюли визуально приглушены
- ✅ Клик по пилюле в режиме `Все` переключает в `Выбрать` без потери выбора
- ✅ Кнопки `все / снять все` работают только в режиме `custom`
- ✅ Сводка снизу обновляется при любом изменении фильтра

### 10.3. Inline-инсайты
- ✅ Если виды одинаковые — info-плашка «Сравнение корректно»
- ✅ Если виды разные в режиме `all` — warn-плашка с описанием различий
- ✅ В режиме `custom` — info-плашка с перечнем выбранных

### 10.4. Адаптивность
- ✅ На мобиле контролы и карточки становятся вертикальными
- ✅ Пилюли активностей скроллятся горизонтально
- ✅ Date-input открывает нативный picker

### 10.5. URL и shareable
- ✅ Все параметры синхронизируются с URL
- ✅ Открытие URL восстанавливает состояние полностью
- ✅ Изменение состояния обновляет URL без перезагрузки (history.replaceState)

### 10.6. Edge cases
- ✅ Невалидные даты показывают подсветку
- ✅ Empty state если фильтр пустой
- ✅ Empty state если в периоде нет данных

---

## 11. План разработки

### Спринт 1 — Базовый компонент (3-4 дня)
- [ ] Маршрут `/comparison` в роутере
- [ ] Layout страницы: header, контролы, сводка
- [ ] `PeriodInputBlock` с двумя date-инпутами и шаблонами
- [ ] `ActivityFilterBlock` с пилюлями и режимами
- [ ] Базовый стор `comparisonStore`
- [ ] Логика синхронизации с URL

### Спринт 2 — Карточки и расчёт (3-4 дня)
- [ ] `PeriodComparisonCard` с разбивкой по видам
- [ ] `ResultCard` с таблицей и дельтой
- [ ] Логика inline-инсайтов
- [ ] Расчёт дельты с цветовой семантикой
- [ ] Empty states

### Спринт 3 — Backend (2-3 дня)
- [ ] Эндпоинт `GET /api/dashboard/comparison`
- [ ] Группировка по видам спорта
- [ ] Расчёт асимметрии
- [ ] Интеграция с фронтом через Tanstack Query

### Спринт 4 — Полировка (2 дня)
- [ ] Адаптивная вёрстка
- [ ] Edge cases и валидация дат
- [ ] Тесты (unit + integration)
- [ ] Loading / error states

---

## 12. Дизайн-токены (доп. к основным)

```css
/* Для блока сравнения периодов */
--cmp-period-1-color: #185FA5;     /* Период 1 — синий */
--cmp-period-2-color: #888780;     /* Период 2 — серый */
--cmp-year-ago-color: #B57FD8;     /* Год назад — фиолетовый (опционально) */

/* Дельта */
--delta-up-bg: #EAF3DE;
--delta-up-text: #3B6D11;
--delta-down-bg: #FCEBEB;
--delta-down-text: #A32D2D;
--delta-flat-bg: #F1EFE8;
--delta-flat-text: #5F5E5A;

/* Insight plates */
--insight-info-bg: #E6F1FB;
--insight-info-text: #185FA5;
--insight-warn-bg: #FAEEDA;
--insight-warn-text: #854F0B;
```

---

## 13. Что НЕ входит в этот этап (на будущее)

Эти возможности сознательно отложены:

1. **Третий период** — для анализа тренда из 3+ микроциклов
2. **Авто-режим фильтра** — система сама определяет, что исключить
3. **Графики сравнения** — линии или парные столбики
4. **Сравнение по типам метрик** — не только часы/км, но и hrTSS, темп, элевация
5. **Сравнение нескольких атлетов** — атлет А vs атлет B в одном периоде
6. **Сохранённые сценарии** — «мои закладки» для частых сравнений
7. **Экспорт сравнения в PDF** — отдельный отчёт сравнения

---

**Конец спецификации.**
