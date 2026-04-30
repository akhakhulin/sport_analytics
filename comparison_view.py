"""
Сравнение периодов — реализация по прототипу
docs/comparison_react/comparison_prototype.html.

Используется:
- pages (если будет создана) — отдельная страница
- dashboard.py, tab2 — внутри главной страницы

Структура (5 блоков):
1. Hero — три большие метрики (Часов / Километров / Активностей)
2. Period controls — два периода в одной карточке через VS-разделитель
3. Activity filter — горизонтальная полоса с toggle и chip'ами
4. Breakdown — парные горизонтальные бары по видам спорта + total
5. Insight — info/warn плашка под содержимым

Префикс ключей разделяет state между разными местами вызова.
"""

from __future__ import annotations

from datetime import date, timedelta

import pandas as pd
import streamlit as st

from sport_icons import sport_icon_html, type_color


_MONTHS_RU = {
    1: "янв", 2: "фев", 3: "мар", 4: "апр", 5: "мая", 6: "июн",
    7: "июл", 8: "авг", 9: "сен", 10: "окт", 11: "ноя", 12: "дек",
}


def _format_date_range(start: date, end: date) -> str:
    if start.year == end.year:
        return (
            f'{start.day} {_MONTHS_RU[start.month]} – '
            f'{end.day} {_MONTHS_RU[end.month]} {end.year}'
        )
    return (
        f'{start.day} {_MONTHS_RU[start.month]} {start.year} – '
        f'{end.day} {_MONTHS_RU[end.month]} {end.year}'
    )


def _pluralize(n: int, forms: tuple[str, str, str]) -> str:
    """forms = (1, 2-4, 5+) — для русского склонения."""
    mod10 = n % 10
    mod100 = n % 100
    if mod10 == 1 and mod100 != 11:
        return forms[0]
    if mod10 in (2, 3, 4) and mod100 not in (12, 13, 14):
        return forms[1]
    return forms[2]


def _fmt_hours(h: float) -> str:
    return f"{h:.1f}"


def _fmt_km(km: float) -> str:
    return f"{km:.0f}" if km >= 100 else f"{km:.1f}"


def _slug(s: str) -> str:
    """ascii_lower + '_' для CSS-friendly id чипа."""
    out: list[str] = []
    for ch in s.lower():
        if ch.isascii() and (ch.isalnum() or ch in "-_"):
            out.append(ch)
        else:
            out.append("_")
    res = "".join(out).strip("_")
    return res or "x"


def _compute_delta(v1: float, v2: float) -> tuple[float, float, str]:
    abs_d = v1 - v2
    pct = (abs_d / v2 * 100) if v2 > 0 else (100.0 if v1 > 0 else 0.0)
    if abs(pct) < 5:
        direction = "flat"
    elif abs_d > 0:
        direction = "up"
    else:
        direction = "down"
    return abs_d, pct, direction


def _delta_badge(
    abs_d: float, pct: float, direction: str,
    unit: str = "", size: str = "md",
    show_abs: bool = True, show_pct: bool = True,
) -> str:
    """Цветная плашка дельты — копирует .delta из прототипа."""
    if direction == "flat":
        bg, fg, arrow = "#F1EFE8", "#5F5E5A", "≈"
    elif direction == "up":
        bg, fg, arrow = "#EAF3DE", "#3B6D11", "↑"
    else:
        bg, fg, arrow = "#FCEBEB", "#A32D2D", "↓"
    sign = "+" if abs_d > 0 else ""
    abs_val = (
        f"{abs_d:.0f}" if abs(abs_d) >= 100 else f"{abs_d:.1f}"
    )
    pct_val = f"{sign}{pct:.0f}%"
    padding = "3px 9px" if size == "md" else "2px 7px"
    fontsz = "12px" if size == "md" else "10px"
    parts: list[str] = [f"<span>{arrow}</span>"]
    if show_abs:
        unit_part = f" {unit}" if unit else ""
        parts.append(f"<span>{sign}{abs_val}{unit_part}</span>")
    if show_abs and show_pct:
        parts.append('<span style="opacity:0.6">·</span>')
    if show_pct:
        parts.append(f"<span>{pct_val}</span>")
    return (
        f'<span style="display:inline-flex; align-items:center; gap:4px; '
        f'border-radius:4px; font-weight:600; font-variant-numeric:tabular-nums; '
        f'background:{bg}; color:{fg}; padding:{padding}; font-size:{fontsz};">'
        f'{"".join(parts)}'
        f'</span>'
    )


def render(
    df: pd.DataFrame,
    *,
    key_prefix: str = "cmp",
    show_title: bool = True,
) -> None:
    """Рендерит UI сравнения двух периодов по прототипу.

    df — DataFrame активностей с колонками:
      day, activity_type_ru, duration_h, distance_km, activity_id
    key_prefix — префикс session_state и widget-ключей.
    show_title — показывать ли header (Title + subtitle).
    """

    K = key_prefix

    # ===== Стили (по comparison_prototype.html) =====
    # Стилизуем только наши компоненты через .st-key-{K}_*; остальной CSS
    # уже задан в static/dashboard.css. Inline-html-блоки внутри карточек
    # стилизуются классами `cmp-*` ниже.
    st.markdown(
        f"""<style>
.st-key-{K}_hero, .st-key-{K}_controls,
.st-key-{K}_filter, .st-key-{K}_breakdown,
.st-key-{K}_insight {{
  background: #FFFFFF !important;
  border-radius: 10px !important;
  border: 0.5px solid rgba(0,0,0,0.08) !important;
  padding: 14px !important;
  margin-bottom: 8px !important;
}}
.st-key-{K}_hero {{
  background: linear-gradient(135deg, #FFFFFF 0%, #F5F4EF 100%) !important;
  padding: 18px 20px !important;
}}

.cmp-h-uppercase {{ font-size:10px; color:#5F5E5A; text-transform:uppercase;
  letter-spacing:0.6px; font-weight:600; margin-bottom:10px; }}
.cmp-hero-grid {{ display:grid; grid-template-columns:1fr 1fr 1fr; gap:14px; }}
.cmp-hero-name {{ font-size:10px; color:#5F5E5A; text-transform:uppercase;
  letter-spacing:0.4px; font-weight:500; margin-bottom:3px; }}
.cmp-hero-row {{ display:flex; align-items:baseline; gap:8px; flex-wrap:wrap;
  margin-bottom:4px; }}
.cmp-hero-cur {{ font-size:28px; font-weight:600; line-height:1;
  letter-spacing:-0.5px; font-variant-numeric:tabular-nums; }}
.cmp-hero-vs {{ font-size:11px; color:#5F5E5A; }}
.cmp-hero-prev {{ font-size:14px; color:#5F5E5A; font-weight:500;
  font-variant-numeric:tabular-nums; }}

.cmp-period-label {{ display:flex; align-items:center; gap:6px; font-size:10px;
  font-weight:600; color:#5F5E5A; text-transform:uppercase; letter-spacing:0.5px;
  margin-bottom:6px; }}
.cmp-dot {{ width:8px; height:8px; border-radius:50%; display:inline-block; }}
.cmp-dot-cur {{ background:#185FA5; }}
.cmp-dot-cmp {{ background:#888780; }}

.cmp-vs-circle {{ width:28px; height:28px; background:#F5F4EF; border-radius:50%;
  display:flex; align-items:center; justify-content:center; font-size:10px;
  font-weight:600; color:#5F5E5A; margin: 16px auto 0; }}

.cmp-meta {{ font-size:10px; color:#888780; font-variant-numeric:tabular-nums;
  margin-top:4px; }}
.cmp-meta b {{ color:#2C2C2A; font-weight:500; }}

/* === Streamlit native widgets — патчим под прототип === */

/* Date-input: компактная высота, бежевый фон, без рамки, формат как
   в прототипе. Стилизуем root + сам <input>. */
.st-key-{K}_p1_start [data-baseweb="input"],
.st-key-{K}_p1_end [data-baseweb="input"],
.st-key-{K}_p2_start [data-baseweb="input"],
.st-key-{K}_p2_end [data-baseweb="input"] {{
  background: #F5F4EF !important;
  border: 0.5px solid transparent !important;
  border-radius: 4px !important;
  min-height: 32px !important;
}}
.st-key-{K}_p1_start input,
.st-key-{K}_p1_end input,
.st-key-{K}_p2_start input,
.st-key-{K}_p2_end input {{
  font-size: 12px !important;
  font-variant-numeric: tabular-nums !important;
  padding: 6px 8px !important;
  height: 30px !important;
  background: transparent !important;
}}
.st-key-{K}_p1_start [data-baseweb="input"]:focus-within,
.st-key-{K}_p1_end [data-baseweb="input"]:focus-within,
.st-key-{K}_p2_start [data-baseweb="input"]:focus-within,
.st-key-{K}_p2_end [data-baseweb="input"]:focus-within {{
  outline: 2px solid #185FA5 !important;
  outline-offset: -1px !important;
}}
/* Убираем дефолтные label-margin у date-input */
.st-key-{K}_p1_start [data-testid="stDateInput"],
.st-key-{K}_p1_end [data-testid="stDateInput"],
.st-key-{K}_p2_start [data-testid="stDateInput"],
.st-key-{K}_p2_end [data-testid="stDateInput"] {{
  margin: 0 !important;
}}

/* Preset buttons → чипы (pill, тонкая рамка, hover info) */
.st-key-{K}_p1_pr7 button, .st-key-{K}_p1_pr14 button,
.st-key-{K}_p1_pr30 button, .st-key-{K}_p1_prcm button,
.st-key-{K}_p2_pr_prev button, .st-key-{K}_p2_pr_year button,
.st-key-{K}_p2_pr_pmon button {{
  height: auto !important;
  min-height: 0 !important;
  padding: 2px 9px !important;
  font-size: 10px !important;
  font-weight: 500 !important;
  border-radius: 12px !important;
  background: transparent !important;
  border: 0.5px solid rgba(0,0,0,0.15) !important;
  color: #5F5E5A !important;
  line-height: 1.6 !important;
  white-space: nowrap !important;
  box-shadow: none !important;
}}
.st-key-{K}_p1_pr7 button:hover, .st-key-{K}_p1_pr14 button:hover,
.st-key-{K}_p1_pr30 button:hover, .st-key-{K}_p1_prcm button:hover,
.st-key-{K}_p2_pr_prev button:hover, .st-key-{K}_p2_pr_year button:hover,
.st-key-{K}_p2_pr_pmon button:hover {{
  background: #E6F1FB !important;
  border-color: #185FA5 !important;
  color: #185FA5 !important;
}}

/* VS-кружок — центрирование по вертикали относительно периодов */
.cmp-vs-circle {{ margin-top: 38px !important; }}

/* Стрелка между датами — без верхнего падинга, чтобы лежала на одной
   линии с инпутами */
.cmp-arrow {{ text-align:center; padding-top:5px; color:#888780; font-size:14px; }}

/* === Activity filter — все элементы в одну строку через flex === */
.st-key-{K}_filter [data-testid="stVerticalBlock"] {{
  flex-direction: row !important;
  flex-wrap: wrap !important;
  align-items: center !important;
  gap: 8px !important;
}}
.st-key-{K}_filter [data-testid="stVerticalBlock"] > [data-testid="stElementContainer"] {{
  width: auto !important;
  margin: 0 !important;
  flex: 0 0 auto !important;
}}

.cmp-filter-label {{ font-size:10px; font-weight:600; color:#5F5E5A;
  text-transform:uppercase; letter-spacing:0.5px; }}
.cmp-filter-vdiv {{ width:0.5px; height:16px; background:rgba(0,0,0,0.15); }}

/* Toggle (segmented_control) внутри filter — компактный */
.st-key-{K}_filter [data-testid="stSegmentedControl"] button {{
  padding: 4px 10px !important;
  font-size: 11px !important;
  min-height: 0 !important;
  height: auto !important;
}}

/* Chip-кнопки видов спорта (default = бежевый pill) */
.st-key-{K}_filter [data-testid="stButton"] > button {{
  height: auto !important;
  min-height: 0 !important;
  padding: 4px 10px 4px 10px !important;
  font-size: 11px !important;
  font-weight: 400 !important;
  border-radius: 12px !important;
  background: #F5F4EF !important;
  border: 0.5px solid transparent !important;
  color: #2C2C2A !important;
  white-space: nowrap !important;
  box-shadow: none !important;
  line-height: 1.4 !important;
}}
.st-key-{K}_filter [data-testid="stButton"] > button:hover {{
  background: #F1EFE8 !important;
}}
/* Выбранный chip (kind="primary") — тёмный фон, белый текст */
.st-key-{K}_filter [data-testid="stButton"] > button[kind="primary"] {{
  background: #2C2C2A !important;
  color: #FFFFFF !important;
  font-weight: 500 !important;
}}
/* «Все / снять» — link-style */
.st-key-{K}_chip_all button, .st-key-{K}_chip_none button {{
  padding: 4px 10px !important;
  font-size: 10px !important;
  background: transparent !important;
  border: 0.5px solid rgba(0,0,0,0.15) !important;
  color: #185FA5 !important;
  border-radius: 12px !important;
}}
.st-key-{K}_chip_all button:hover, .st-key-{K}_chip_none button:hover {{
  background: #E6F1FB !important;
  border-color: #185FA5 !important;
}}

.cmp-bar-row {{ display:grid; grid-template-columns:160px 1fr 110px;
  align-items:center; gap:14px; padding:10px 0;
  border-bottom:0.5px solid rgba(0,0,0,0.06); }}
.cmp-bar-row:last-child {{ border-bottom:none; }}
.cmp-bar-row-name {{ display:flex; align-items:center; gap:8px;
  font-size:12px; font-weight:500; min-width:0; overflow:hidden; }}
.cmp-bar-row-name span:last-child {{ overflow:hidden; text-overflow:ellipsis;
  white-space:nowrap; }}
.cmp-bar-pair {{ display:flex; flex-direction:column; gap:4px; }}
.cmp-bar-track {{ display:flex; align-items:center; gap:8px; height:16px; }}
.cmp-bar-fill-wrap {{ flex:1; height:14px; background:#F5F4EF;
  border-radius:3px; overflow:hidden; }}
.cmp-bar-fill {{ height:100%; border-radius:3px; }}
.cmp-bar-fill-cur {{ background:#185FA5; }}
.cmp-bar-fill-prev {{ background:#B8B6AE; }}
.cmp-bar-value {{ font-size:10px; font-variant-numeric:tabular-nums;
  font-weight:600; min-width:60px; text-align:right; white-space:nowrap; }}
.cmp-bar-value-cur {{ color:#2C2C2A; }}
.cmp-bar-value-prev {{ color:#5F5E5A; }}
.cmp-bar-row-delta {{ text-align:right; }}

.cmp-tag-new {{ display:inline-block; padding:2px 7px; font-size:10px;
  font-weight:600; background:#EAF3DE; color:#3B6D11; border-radius:4px; }}
.cmp-tag-gone {{ display:inline-block; padding:2px 7px; font-size:10px;
  font-weight:600; background:#F1EFE8; color:#5F5E5A; border-radius:4px; }}

.cmp-total-row {{ display:grid; grid-template-columns:160px 1fr 110px;
  gap:14px; padding:12px 0 4px; margin-top:8px;
  border-top:0.5px solid rgba(0,0,0,0.15); font-weight:600; font-size:12px; }}
.cmp-total-vals {{ display:flex; flex-direction:column; gap:3px; }}
.cmp-total-val {{ display:flex; justify-content:space-between; font-size:11px;
  font-variant-numeric:tabular-nums; }}
.cmp-total-val-cur {{ color:#185FA5; }}
.cmp-total-val-prev {{ color:#888780; font-weight:500; }}

.cmp-empty {{ text-align:center; padding:32px; color:#5F5E5A; font-size:12px; }}

.cmp-insight {{ display:flex; align-items:flex-start; gap:10px;
  padding:10px 12px; border-radius:6px; font-size:11px; line-height:1.5; }}
.cmp-insight-icon {{ width:16px; height:16px; border-radius:50%; flex-shrink:0;
  display:flex; align-items:center; justify-content:center; font-size:10px;
  font-weight:700; }}
.cmp-insight-info {{ background:#E6F1FB; color:#185FA5; }}
.cmp-insight-info .cmp-insight-icon {{ background:#185FA5; color:#E6F1FB; }}
.cmp-insight-warn {{ background:#FAEEDA; color:#854F0B; }}
.cmp-insight-warn .cmp-insight-icon {{ background:#854F0B; color:#FAEEDA; }}

@media (max-width: 720px) {{
  .cmp-hero-grid {{ grid-template-columns: 1fr !important; }}
  .cmp-hero-cur {{ font-size: 24px !important; }}
  .cmp-bar-row, .cmp-total-row {{ grid-template-columns: 1fr !important; }}
}}
</style>""",
        unsafe_allow_html=True,
    )

    if show_title:
        st.markdown(
            '<div style="margin-bottom:6px;">'
            '<h1 style="font-size:18px; font-weight:600; margin:0 0 2px 0;">'
            'Сравнение периодов</h1>'
            '<div style="font-size:11px; color:#5F5E5A;">'
            'Гибкий анализ объёма тренировок между двумя периодами</div>'
            '</div>',
            unsafe_allow_html=True,
        )

    # ===== State init (с дефолтами) =====
    today = date.today()
    if f"{K}_p1_start" not in st.session_state:
        st.session_state[f"{K}_p1_start"] = today - timedelta(days=13)
    if f"{K}_p1_end" not in st.session_state:
        st.session_state[f"{K}_p1_end"] = today
    if f"{K}_p2_start" not in st.session_state:
        st.session_state[f"{K}_p2_start"] = today - timedelta(days=27)
    if f"{K}_p2_end" not in st.session_state:
        st.session_state[f"{K}_p2_end"] = today - timedelta(days=14)
    if f"{K}_filter_mode" not in st.session_state:
        st.session_state[f"{K}_filter_mode"] = "Все"
    if f"{K}_selected_sports" not in st.session_state:
        st.session_state[f"{K}_selected_sports"] = []

    # ===== Preset callbacks =====
    def _p1_days(days: int) -> None:
        t = date.today()
        st.session_state[f"{K}_p1_end"] = t
        st.session_state[f"{K}_p1_start"] = t - timedelta(days=days - 1)

    def _p1_curmonth() -> None:
        t = date.today()
        st.session_state[f"{K}_p1_start"] = t.replace(day=1)
        st.session_state[f"{K}_p1_end"] = t

    def _p2_prev_period() -> None:
        s = st.session_state[f"{K}_p1_start"]
        e = st.session_state[f"{K}_p1_end"]
        plen = (e - s).days + 1
        end_d = s - timedelta(days=1)
        start_d = end_d - timedelta(days=plen - 1)
        st.session_state[f"{K}_p2_start"] = start_d
        st.session_state[f"{K}_p2_end"] = end_d

    def _p2_year_ago() -> None:
        s = st.session_state[f"{K}_p1_start"]
        e = st.session_state[f"{K}_p1_end"]
        st.session_state[f"{K}_p2_start"] = s - timedelta(days=365)
        st.session_state[f"{K}_p2_end"] = e - timedelta(days=365)

    def _p2_prev_month() -> None:
        t = date.today()
        first = t.replace(day=1)
        end_d = first - timedelta(days=1)
        start_d = end_d.replace(day=1)
        st.session_state[f"{K}_p2_start"] = start_d
        st.session_state[f"{K}_p2_end"] = end_d

    def _set_filter_all() -> None:
        st.session_state[f"{K}_filter_mode"] = "Все"

    def _set_filter_custom() -> None:
        st.session_state[f"{K}_filter_mode"] = "Выбрать"

    def _toggle_sport(sport: str, all_available: list[str]) -> None:
        mode = st.session_state.get(f"{K}_filter_mode", "Все")
        sel = list(st.session_state.get(f"{K}_selected_sports", []))
        if mode == "Все":
            # Авто-переключение: все остаются выбранными, кроме кликнутого
            sel = [s for s in all_available if s != sport]
            st.session_state[f"{K}_filter_mode"] = "Выбрать"
        else:
            if sport in sel:
                sel = [s for s in sel if s != sport]
            else:
                sel = sel + [sport]
        st.session_state[f"{K}_selected_sports"] = sel

    def _select_all_sports(all_available: list[str]) -> None:
        st.session_state[f"{K}_selected_sports"] = list(all_available)

    def _deselect_all_sports() -> None:
        st.session_state[f"{K}_selected_sports"] = []

    # ===== Data computation =====
    def _period_view(start_d: date, end_d: date) -> pd.DataFrame:
        if df.empty:
            return df
        mask = (df["day"] >= start_d) & (df["day"] <= end_d)
        return df[mask]

    def _period_groups(view: pd.DataFrame) -> pd.DataFrame:
        if view.empty:
            return pd.DataFrame(columns=[
                "activity_type_ru", "hours", "km", "count",
            ])
        return (
            view.groupby("activity_type_ru")
            .agg(
                hours=("duration_h", "sum"),
                km=("distance_km", "sum"),
                count=("activity_id", "count"),
            )
            .reset_index()
            .sort_values("hours", ascending=False)
        )

    p1s = st.session_state[f"{K}_p1_start"]
    p1e = st.session_state[f"{K}_p1_end"]
    p2s = st.session_state[f"{K}_p2_start"]
    p2e = st.session_state[f"{K}_p2_end"]

    p1_view = _period_view(p1s, p1e)
    p2_view = _period_view(p2s, p2e)
    p1_grp = _period_groups(p1_view)
    p2_grp = _period_groups(p2_view)

    p1_sports_all = list(p1_grp["activity_type_ru"]) if not p1_grp.empty else []
    p2_sports_all = list(p2_grp["activity_type_ru"]) if not p2_grp.empty else []
    all_sports = sorted(set(p1_sports_all) | set(p2_sports_all))

    mode = st.session_state.get(f"{K}_filter_mode", "Все")
    selected_sports = list(st.session_state.get(f"{K}_selected_sports", []))
    if mode == "Все":
        included = list(all_sports)
    else:
        included = [s for s in selected_sports if s in all_sports]

    def _totals(grp: pd.DataFrame) -> dict:
        if grp.empty:
            return {"hours": 0.0, "km": 0.0, "count": 0}
        sub = grp[grp["activity_type_ru"].isin(included)]
        return {
            "hours": float(sub["hours"].sum()),
            "km": float(sub["km"].sum()),
            "count": int(sub["count"].sum()),
        }

    p1_totals = _totals(p1_grp)
    p2_totals = _totals(p2_grp)

    # ===== 1. HERO =====
    with st.container(key=f"{K}_hero"):
        h_abs, h_pct, h_dir = _compute_delta(p1_totals["hours"], p2_totals["hours"])
        k_abs, k_pct, k_dir = _compute_delta(p1_totals["km"], p2_totals["km"])
        a_abs, a_pct, a_dir = _compute_delta(p1_totals["count"], p2_totals["count"])
        st.markdown(
            f'<div class="cmp-h-uppercase">⚡ Главный результат</div>'
            f'<div class="cmp-hero-grid">'
            # Hours
            f'<div>'
            f'  <div class="cmp-hero-name">Часов</div>'
            f'  <div class="cmp-hero-row">'
            f'    <span class="cmp-hero-cur">{p1_totals["hours"]:.1f}</span>'
            f'    <span class="cmp-hero-vs">vs</span>'
            f'    <span class="cmp-hero-prev">{p2_totals["hours"]:.1f}</span>'
            f'  </div>'
            f'  {_delta_badge(h_abs, h_pct, h_dir, "ч", "md")}'
            f'</div>'
            # Km
            f'<div>'
            f'  <div class="cmp-hero-name">Километров</div>'
            f'  <div class="cmp-hero-row">'
            f'    <span class="cmp-hero-cur">{_fmt_km(p1_totals["km"])}</span>'
            f'    <span class="cmp-hero-vs">vs</span>'
            f'    <span class="cmp-hero-prev">{_fmt_km(p2_totals["km"])}</span>'
            f'  </div>'
            f'  {_delta_badge(k_abs, k_pct, k_dir, "км", "md")}'
            f'</div>'
            # Activities
            f'<div>'
            f'  <div class="cmp-hero-name">Активностей</div>'
            f'  <div class="cmp-hero-row">'
            f'    <span class="cmp-hero-cur">{p1_totals["count"]}</span>'
            f'    <span class="cmp-hero-vs">vs</span>'
            f'    <span class="cmp-hero-prev">{p2_totals["count"]}</span>'
            f'  </div>'
            f'  {_delta_badge(a_abs, a_pct, a_dir, "", "md")}'
            f'</div>'
            f'</div>',
            unsafe_allow_html=True,
        )

    # ===== 2. PERIOD CONTROLS =====
    with st.container(key=f"{K}_controls"):
        cols = st.columns([10, 1, 10])

        with cols[0]:
            st.markdown(
                '<div class="cmp-period-label">'
                '<span class="cmp-dot cmp-dot-cur"></span>'
                'Период 1 · основной</div>',
                unsafe_allow_html=True,
            )
            d_cols = st.columns([2, 1, 2])
            with d_cols[0]:
                st.date_input(
                    "От", key=f"{K}_p1_start", label_visibility="collapsed",
                )
            with d_cols[1]:
                st.markdown(
                    '<div class="cmp-arrow">→</div>',
                    unsafe_allow_html=True,
                )
            with d_cols[2]:
                st.date_input(
                    "До", key=f"{K}_p1_end", label_visibility="collapsed",
                )
            pcols = st.columns(4)
            with pcols[0]:
                st.button("7д", key=f"{K}_p1_pr7",
                          on_click=_p1_days, args=(7,),
                          use_container_width=True)
            with pcols[1]:
                st.button("14д", key=f"{K}_p1_pr14",
                          on_click=_p1_days, args=(14,),
                          use_container_width=True)
            with pcols[2]:
                st.button("30д", key=f"{K}_p1_pr30",
                          on_click=_p1_days, args=(30,),
                          use_container_width=True)
            with pcols[3]:
                st.button("месяц", key=f"{K}_p1_prcm",
                          on_click=_p1_curmonth,
                          use_container_width=True)
            p1_days_n = (p1e - p1s).days + 1
            p1_act_n = int(p1_view.shape[0]) if not p1_view.empty else 0
            st.markdown(
                f'<div class="cmp-meta">'
                f'{p1_days_n} {_pluralize(p1_days_n, ("день","дня","дней"))}'
                f' · {p1_act_n} '
                f'{_pluralize(p1_act_n, ("активность","активности","активностей"))}'
                f'</div>',
                unsafe_allow_html=True,
            )

        with cols[1]:
            st.markdown(
                '<div class="cmp-vs-circle">VS</div>',
                unsafe_allow_html=True,
            )

        with cols[2]:
            st.markdown(
                '<div class="cmp-period-label">'
                '<span class="cmp-dot cmp-dot-cmp"></span>'
                'Период 2 · сравнение</div>',
                unsafe_allow_html=True,
            )
            d_cols = st.columns([2, 1, 2])
            with d_cols[0]:
                st.date_input(
                    "От", key=f"{K}_p2_start", label_visibility="collapsed",
                )
            with d_cols[1]:
                st.markdown(
                    '<div class="cmp-arrow">→</div>',
                    unsafe_allow_html=True,
                )
            with d_cols[2]:
                st.date_input(
                    "До", key=f"{K}_p2_end", label_visibility="collapsed",
                )
            pcols = st.columns(3)
            with pcols[0]:
                st.button("пред. равный", key=f"{K}_p2_pr_prev",
                          on_click=_p2_prev_period,
                          use_container_width=True)
            with pcols[1]:
                st.button("год назад", key=f"{K}_p2_pr_year",
                          on_click=_p2_year_ago,
                          use_container_width=True)
            with pcols[2]:
                st.button("прошл. месяц", key=f"{K}_p2_pr_pmon",
                          on_click=_p2_prev_month,
                          use_container_width=True)
            p2_days_n = (p2e - p2s).days + 1
            p2_act_n = int(p2_view.shape[0]) if not p2_view.empty else 0
            st.markdown(
                f'<div class="cmp-meta">'
                f'{p2_days_n} {_pluralize(p2_days_n, ("день","дня","дней"))}'
                f' · {p2_act_n} '
                f'{_pluralize(p2_act_n, ("активность","активности","активностей"))}'
                f'</div>',
                unsafe_allow_html=True,
            )

    # ===== 3. ACTIVITY FILTER =====
    # Все элементы (метка / toggle / divider / chips / actions) в одной
    # строке через CSS-flex (см. .st-key-{K}_filter правило выше).
    # Цветная точка для каждого chip — ::before c фоном type_color(sport),
    # генерируется динамически ниже.
    if all_sports:
        chip_css_rules = []
        for sport in all_sports:
            slug = _slug(sport)
            color = type_color(sport)
            chip_css_rules.append(
                f'.st-key-{K}_chip_{slug} button::before {{'
                f' content:""; display:inline-block; width:8px; height:8px;'
                f' border-radius:50%; background:{color};'
                f' margin-right:6px; vertical-align:middle; flex-shrink:0; }}'
            )
        st.markdown(
            "<style>" + "\n".join(chip_css_rules) + "</style>",
            unsafe_allow_html=True,
        )

    with st.container(key=f"{K}_filter"):
        st.markdown(
            '<div class="cmp-filter-label">Активности:</div>',
            unsafe_allow_html=True,
        )
        st.segmented_control(
            "Режим",
            ["Все", "Выбрать"],
            default=st.session_state.get(f"{K}_filter_mode", "Все"),
            selection_mode="single",
            key=f"{K}_filter_mode",
            label_visibility="collapsed",
        )
        st.markdown(
            '<div class="cmp-filter-vdiv"></div>',
            unsafe_allow_html=True,
        )

        if all_sports:
            mode_now = st.session_state.get(f"{K}_filter_mode", "Все")
            for sport in all_sports:
                is_on = (
                    mode_now == "Все" or sport in st.session_state.get(
                        f"{K}_selected_sports", [],
                    )
                )
                btn_type = (
                    "primary" if (mode_now == "Выбрать" and is_on)
                    else "secondary"
                )
                st.button(
                    sport,
                    key=f"{K}_chip_{_slug(sport)}",
                    on_click=_toggle_sport,
                    args=(sport, all_sports),
                    type=btn_type,
                )
            # «Все / Снять» только в режиме Выбрать
            if mode_now == "Выбрать":
                st.button(
                    "✓ все",
                    key=f"{K}_chip_all",
                    on_click=_select_all_sports,
                    args=(all_sports,),
                )
                st.button(
                    "✗ снять",
                    key=f"{K}_chip_none",
                    on_click=_deselect_all_sports,
                )

    # ===== 4. BREAKDOWN =====
    with st.container(key=f"{K}_breakdown"):
        p1_range = _format_date_range(p1s, p1e)
        p2_range = _format_date_range(p2s, p2e)

        # Заголовок + легенда
        st.markdown(
            f'<div style="display:flex; align-items:center; gap:8px; '
            f'font-size:13px; font-weight:600; margin-bottom:14px; '
            f'flex-wrap:wrap;">'
            f'<span>📊 Разбивка по видам спорта · часы</span>'
            f'<div style="display:flex; gap:12px; font-size:10px; color:#5F5E5A; '
            f'font-weight:400; margin-left:auto; align-items:center; flex-wrap:wrap;">'
            f'<span style="display:flex; align-items:center; gap:5px;">'
            f'<span style="display:inline-block; width:12px; height:8px; '
            f'border-radius:2px; background:#185FA5;"></span>{p1_range}</span>'
            f'<span style="display:flex; align-items:center; gap:5px;">'
            f'<span style="display:inline-block; width:12px; height:8px; '
            f'border-radius:2px; background:#B8B6AE;"></span>{p2_range}</span>'
            f'</div>'
            f'</div>',
            unsafe_allow_html=True,
        )

        # Объединённый список видов из обоих периодов с фильтром
        rows: list[dict] = []
        for sport in all_sports:
            if sport not in included:
                continue
            r1 = p1_grp[p1_grp["activity_type_ru"] == sport]
            r2 = p2_grp[p2_grp["activity_type_ru"] == sport]
            h1 = float(r1["hours"].iloc[0]) if not r1.empty else 0.0
            h2 = float(r2["hours"].iloc[0]) if not r2.empty else 0.0
            km1 = float(r1["km"].iloc[0]) if not r1.empty else 0.0
            km2 = float(r2["km"].iloc[0]) if not r2.empty else 0.0
            rows.append({
                "name": sport,
                "h1": h1, "h2": h2,
                "km1": km1, "km2": km2,
                "only_in_1": (not r1.empty) and r2.empty,
                "only_in_2": r1.empty and (not r2.empty),
            })
        rows.sort(key=lambda r: r["h1"] + r["h2"], reverse=True)

        if not rows:
            st.markdown(
                '<div class="cmp-empty">⚠️ Нет данных для отображения. '
                'Выбери хотя бы один вид спорта в фильтре.</div>',
                unsafe_allow_html=True,
            )
        else:
            max_h = max([max(r["h1"], r["h2"]) for r in rows] + [0.001])
            rows_html = ""
            for r in rows:
                w1 = (r["h1"] / max_h) * 100 if max_h > 0 else 0
                w2 = (r["h2"] / max_h) * 100 if max_h > 0 else 0
                color = type_color(r["name"])
                icon = sport_icon_html(r["name"], size=18, color=color)
                if r["only_in_1"]:
                    badge = '<span class="cmp-tag-new">+ новый</span>'
                elif r["only_in_2"]:
                    badge = '<span class="cmp-tag-gone">− исчез</span>'
                else:
                    d_abs, d_pct, d_dir = _compute_delta(r["h1"], r["h2"])
                    badge = _delta_badge(
                        d_abs, d_pct, d_dir, "", "sm",
                        show_abs=False, show_pct=True,
                    )
                v1 = f'{r["h1"]:.1f} ч' if r["h1"] > 0 else '—'
                v2 = f'{r["h2"]:.1f} ч' if r["h2"] > 0 else '—'
                rows_html += (
                    f'<div class="cmp-bar-row">'
                    f'  <div class="cmp-bar-row-name">'
                    f'    <span style="display:inline-block; width:10px; height:10px; '
                    f'border-radius:50%; background:{color}; flex-shrink:0;"></span>'
                    f'    {icon}'
                    f'    <span>{r["name"]}</span>'
                    f'  </div>'
                    f'  <div class="cmp-bar-pair">'
                    f'    <div class="cmp-bar-track">'
                    f'      <div class="cmp-bar-fill-wrap">'
                    f'        <div class="cmp-bar-fill cmp-bar-fill-cur" '
                    f'style="width:{w1}%;"></div>'
                    f'      </div>'
                    f'      <span class="cmp-bar-value cmp-bar-value-cur">{v1}</span>'
                    f'    </div>'
                    f'    <div class="cmp-bar-track">'
                    f'      <div class="cmp-bar-fill-wrap">'
                    f'        <div class="cmp-bar-fill cmp-bar-fill-prev" '
                    f'style="width:{w2}%;"></div>'
                    f'      </div>'
                    f'      <span class="cmp-bar-value cmp-bar-value-prev">{v2}</span>'
                    f'    </div>'
                    f'  </div>'
                    f'  <div class="cmp-bar-row-delta">{badge}</div>'
                    f'</div>'
                )

            t_abs, t_pct, t_dir = _compute_delta(p1_totals["hours"], p2_totals["hours"])
            total_html = (
                f'<div class="cmp-total-row">'
                f'  <div>Итого</div>'
                f'  <div class="cmp-total-vals">'
                f'    <div class="cmp-total-val cmp-total-val-cur">'
                f'      <span>{p1_range}</span>'
                f'      <span>{_fmt_hours(p1_totals["hours"])} ч · '
                f'{_fmt_km(p1_totals["km"])} км</span>'
                f'    </div>'
                f'    <div class="cmp-total-val cmp-total-val-prev">'
                f'      <span>{p2_range}</span>'
                f'      <span>{_fmt_hours(p2_totals["hours"])} ч · '
                f'{_fmt_km(p2_totals["km"])} км</span>'
                f'    </div>'
                f'  </div>'
                f'  <div style="text-align:right;">'
                f'{_delta_badge(t_abs, t_pct, t_dir, "ч", "sm", show_abs=False, show_pct=True)}'
                f'  </div>'
                f'</div>'
            )
            st.markdown(rows_html + total_html, unsafe_allow_html=True)

    # ===== 5. INSIGHT =====
    with st.container(key=f"{K}_insight"):
        if mode == "Все":
            keys1 = set(p1_sports_all)
            keys2 = set(p2_sports_all)
            only_in_1 = sorted(keys1 - keys2)
            only_in_2 = sorted(keys2 - keys1)
            if not only_in_1 and not only_in_2:
                st.markdown(
                    '<div class="cmp-insight cmp-insight-info">'
                    '<span class="cmp-insight-icon">i</span>'
                    '<div>Все виды активности присутствуют в обоих периодах. '
                    'Сравнение полностью корректно.</div>'
                    '</div>',
                    unsafe_allow_html=True,
                )
            else:
                parts: list[str] = []
                if only_in_1:
                    parts.append(
                        f'<b>Виды только в Период 1:</b> '
                        f'{", ".join(only_in_1)}.'
                    )
                if only_in_2:
                    parts.append(
                        f'<b>Виды только в Период 2:</b> '
                        f'{", ".join(only_in_2)}.'
                    )
                msg = " ".join(parts) + (
                    " Это влияет на сравнение часов и километров. "
                    "Если нужно «честное» сравнение — переключись на «Выбрать» и оставь общие виды."
                )
                st.markdown(
                    f'<div class="cmp-insight cmp-insight-warn">'
                    f'<span class="cmp-insight-icon">!</span>'
                    f'<div>{msg}</div>'
                    f'</div>',
                    unsafe_allow_html=True,
                )
        else:
            if not selected_sports:
                st.markdown(
                    '<div class="cmp-insight cmp-insight-warn">'
                    '<span class="cmp-insight-icon">!</span>'
                    '<div>Не выбрано ни одной активности. '
                    'Выбери хотя бы один вид выше.</div>'
                    '</div>',
                    unsafe_allow_html=True,
                )
            else:
                names = [s for s in selected_sports if s in all_sports]
                st.markdown(
                    f'<div class="cmp-insight cmp-insight-info">'
                    f'<span class="cmp-insight-icon">i</span>'
                    f'<div>Сравниваются только выбранные виды: '
                    f'<b>{", ".join(names)}</b>.</div>'
                    f'</div>',
                    unsafe_allow_html=True,
                )
