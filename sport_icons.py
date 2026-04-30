"""
Иконки и цвета видов спорта — общий модуль для дашборда и сравнения.

Сейчас используется только comparison_view.py; в dashboard.py локальные
копии тех же функций (исторически), при следующем рефакторе их можно
переключить на импорт отсюда.
"""

from __future__ import annotations

# === Базовые цвета трёх главных групп ===
SPORT_COLORS: dict[str, str] = {
    "Бег": "#97C459",
    "Велосипед": "#378ADD",
    "Плавание": "#1D9E75",
}

# Запасная палитра для типов вне трёх основных групп (лыжи, лыжероллеры и т.п.)
_TYPE_FALLBACK_PALETTE: list[str] = [
    "#5F4FB0",  # фиолетовый
    "#D85A30",  # оранжевый
    "#0F6E56",  # тёмно-зелёный
    "#854F0B",  # коричневый
    "#A32D2D",  # красный
    "#185FA5",  # тёмно-синий
    "#888780",  # серый
]

# === SVG-иконки видов спорта (минималистичный line-art, 24x24) ===
# Источник: docs/sport_icons_pack.html
_SPORT_ICONS_SVG: dict[str, str] = {
    "run": '<g fill="none" stroke="currentColor" stroke-width="1.8" stroke-linecap="round" stroke-linejoin="round"><circle cx="14.5" cy="4.5" r="1.8" fill="currentColor"/><path d="M5 21l3-5 4-2 1-5 4 4 4 0"/><path d="M9 13l3-3 4 2"/><path d="M5.5 9l3-1.5 2 1.5"/></g>',
    "bike": '<g fill="none" stroke="currentColor" stroke-width="1.6" stroke-linecap="round" stroke-linejoin="round"><circle cx="5.5" cy="17.5" r="3.5"/><circle cx="18.5" cy="17.5" r="3.5"/><circle cx="14" cy="4.5" r="1.5" fill="currentColor"/><path d="M5.5 17.5l4-7.5h6l3 7.5"/><path d="M9.5 10l-1.5-3h-2"/><path d="M15.5 10l-1.5-2.5"/><path d="M12.5 14l-3 3.5"/></g>',
    "swim": '<g fill="none" stroke="currentColor" stroke-width="1.6" stroke-linecap="round" stroke-linejoin="round"><circle cx="17" cy="6" r="1.6" fill="currentColor"/><path d="M3 11l5-3 5 4 5-2"/><path d="M2 16q2 -1.5 4 0t4 0t4 0t4 0t4 0"/><path d="M2 20q2 -1.5 4 0t4 0t4 0t4 0t4 0"/></g>',
    "ski_skate": '<g fill="none" stroke="currentColor" stroke-width="1.6" stroke-linecap="round" stroke-linejoin="round"><circle cx="13" cy="3.5" r="1.6" fill="currentColor"/><path d="M11 7l2 2 -1 4 3 2"/><path d="M3 21l7-9"/><path d="M11 21l9-7"/><path d="M9 6l-3 1"/><path d="M16 11l3 -1"/></g>',
    "ski_classic": '<g fill="none" stroke="currentColor" stroke-width="1.6" stroke-linecap="round" stroke-linejoin="round"><circle cx="13" cy="3.5" r="1.6" fill="currentColor"/><path d="M11.5 6.5l1.5 3 -1 4 3 2"/><path d="M2 21l8 -3"/><path d="M14 21l8 -3"/><path d="M5 8l-1 12"/><path d="M19 8l1 12"/></g>',
    "ski": '<g fill="none" stroke="currentColor" stroke-width="1.6" stroke-linecap="round" stroke-linejoin="round"><circle cx="13" cy="3.5" r="1.6" fill="currentColor"/><path d="M12 6l1 3l-1 4l3 2"/><line x1="3" y1="20" x2="20" y2="14"/><line x1="6" y1="22" x2="22" y2="16"/></g>',
    "strength": '<g fill="none" stroke="currentColor" stroke-width="1.8" stroke-linecap="round" stroke-linejoin="round"><rect x="2" y="9" width="3" height="6" rx="0.5"/><rect x="19" y="9" width="3" height="6" rx="0.5"/><rect x="5" y="10.5" width="2" height="3" rx="0.3"/><rect x="17" y="10.5" width="2" height="3" rx="0.3"/><line x1="7" y1="12" x2="17" y2="12"/></g>',
    "treadmill": '<g fill="none" stroke="currentColor" stroke-width="1.5" stroke-linecap="round" stroke-linejoin="round"><circle cx="11" cy="4.5" r="1.5" fill="currentColor"/><path d="M7 13l2 -3l3 -1l-1 -3l2 2l3 0"/><path d="M3 18l3 -2l13 0l3 2"/><line x1="3" y1="20" x2="21" y2="20"/><line x1="14" y1="9" x2="18" y2="6"/></g>',
    "bike_stationary": '<g fill="none" stroke="currentColor" stroke-width="1.5" stroke-linecap="round" stroke-linejoin="round"><circle cx="14" cy="4" r="1.5" fill="currentColor"/><circle cx="9" cy="16" r="3.5"/><path d="M11 9l3 -2l1 4l-2 3"/><line x1="14" y1="2" x2="14" y2="20"/><line x1="11" y1="20" x2="17" y2="20"/><line x1="14" y1="11" x2="20" y2="11"/></g>',
    "rowing": '<g fill="none" stroke="currentColor" stroke-width="1.6" stroke-linecap="round" stroke-linejoin="round"><circle cx="9" cy="5" r="1.6" fill="currentColor"/><path d="M3 13l4 -3 5 1 6 -4"/><path d="M7 10l1 4"/><path d="M11 11l-2 5"/><path d="M2 19q2 -1.5 4 0t4 0t4 0t4 0t4 0"/></g>',
    "yoga": '<g fill="none" stroke="currentColor" stroke-width="1.6" stroke-linecap="round" stroke-linejoin="round"><circle cx="12" cy="4.5" r="1.6" fill="currentColor"/><path d="M12 7l0 6"/><path d="M12 9l-5 2l5 0"/><path d="M12 9l5 2l-5 0"/><path d="M7 18l5 -5l5 5"/><path d="M5 19l14 0"/></g>',
    "hike": '<g fill="none" stroke="currentColor" stroke-width="1.6" stroke-linecap="round" stroke-linejoin="round"><circle cx="14" cy="4.5" r="1.6" fill="currentColor"/><path d="M5 21l3 -5l4 -1l-1 -5l4 4l3 0"/><path d="M9 14l4 -3"/><path d="M3 21l4 -10l4 -1l5 -5l5 16"/></g>',
    "walk": '<g fill="none" stroke="currentColor" stroke-width="1.8" stroke-linecap="round" stroke-linejoin="round"><circle cx="13" cy="4.5" r="1.7" fill="currentColor"/><path d="M7 21l3 -5l3 -2l-1 -4l3 3l3 1"/><path d="M10 14l2 -3"/><path d="M9 9l3 -1l3 2"/></g>',
    "other": '<g fill="none" stroke="currentColor" stroke-width="1.6" stroke-linecap="round" stroke-linejoin="round"><circle cx="12" cy="12" r="9"/><path d="M12 7v5l3 3"/></g>',
}

# Маппинг activity_type_ru → ключ иконки
_ACTIVITY_ICON_MAP: dict[str, str] = {
    "Бег": "run",
    "Беговая дорожка": "treadmill",
    "Трейл": "run",
    "Стадион": "run",
    "Виртуальный бег": "treadmill",
    "Велосипед": "bike",
    "Велотренажёр": "bike_stationary",
    "Шоссейный велосипед": "bike",
    "Маунтинбайк": "bike",
    "Гравел": "bike",
    "Виртуальная вело": "bike_stationary",
    "Бассейн": "swim",
    "Открытая вода": "swim",
    "Плавание": "swim",
    "Силовая": "strength",
    "Лыжи · конёк": "ski_skate",
    "Лыжи · классика": "ski_classic",
    "Лыжероллеры · конёк": "ski_skate",
    "Лыжероллеры · классика": "ski_classic",
    "Йога": "yoga",
    "Пилатес": "yoga",
    "Кардио": "other",
}


def sport_group(t: str | None) -> str:
    if t in ("Бег", "Беговая дорожка", "Трейл", "Стадион", "Виртуальный бег"):
        return "Бег"
    if t in (
        "Велосипед", "Велотренажёр", "Шоссейный велосипед",
        "Маунтинбайк", "Гравел", "Виртуальная вело",
    ):
        return "Велосипед"
    if t in ("Бассейн", "Открытая вода", "Плавание"):
        return "Плавание"
    return "Прочее"


def type_color(t: str | None) -> str:
    """Цвет конкретной активности.

    Логика: явные цвета для лыж/лыжероллеров, SPORT_COLORS для главных
    трёх групп, иначе стабильный из fallback-палитры по hash.
    """
    if isinstance(t, str):
        if "конёк" in t.lower() or "конек" in t.lower():
            if t.startswith("Лыжероллеры"):
                return "#5F4FB0"
            return "#4A6FA5"
        if "классика" in t.lower():
            if t.startswith("Лыжероллеры"):
                return "#8B6FB5"
            return "#6B8AB5"
        if t.startswith("Лыжи"):
            return "#4A6FA5"
        if t.startswith("Лыжероллеры"):
            return "#5F4FB0"
    grp = sport_group(t)
    if grp in SPORT_COLORS:
        return SPORT_COLORS[grp]
    return _TYPE_FALLBACK_PALETTE[abs(hash(t or "")) % len(_TYPE_FALLBACK_PALETTE)]


def sport_icon_html(activity_type_ru: str | None, size: int = 18, color: str | None = None) -> str:
    """Inline SVG-иконка вида спорта."""
    name = _ACTIVITY_ICON_MAP.get(activity_type_ru or "", "other")
    body = _SPORT_ICONS_SVG.get(name, _SPORT_ICONS_SVG["other"])
    c = color or type_color(activity_type_ru)
    return (
        f'<svg width="{size}" height="{size}" viewBox="0 0 24 24" '
        f'style="color:{c}; flex-shrink:0; vertical-align:middle;">{body}</svg>'
    )
