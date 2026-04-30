"""
Общий рендер блока «Сравнение периодов».
Спека: docs/Сравнение периодов/SPECIFICATION_period_comparison.md

Используется:
- pages/1_📊_Сравнение_периодов.py — отдельная страница (key_prefix="cmp_page")
- dashboard.py, tab2 — внутри главной страницы (key_prefix="cmp_tab")

Префикс ключей разделяет state между двумя местами, чтобы выбор на
странице не перетирал выбор в tab2 и наоборот.
"""

from __future__ import annotations

from datetime import date, timedelta

import pandas as pd
import streamlit as st


_MONTHS_RU = {
    1: "янв", 2: "фев", 3: "мар", 4: "апр", 5: "мая", 6: "июн",
    7: "июл", 8: "авг", 9: "сен", 10: "окт", 11: "ноя", 12: "дек",
}


def _format_period(start: date, end: date) -> str:
    if start.year == end.year:
        return (
            f'{start.day} {_MONTHS_RU[start.month]} – '
            f'{end.day} {_MONTHS_RU[end.month]} {end.year}'
        )
    return (
        f'{start.day} {_MONTHS_RU[start.month]} {start.year} – '
        f'{end.day} {_MONTHS_RU[end.month]} {end.year}'
    )


def _delta(v1: float, v2: float) -> tuple[float, float, str]:
    abs_d = v1 - v2
    pct = (abs_d / v2 * 100) if v2 > 0 else (100.0 if v1 > 0 else 0.0)
    if abs(pct) < 5:
        direction = "flat"
    elif abs_d > 0:
        direction = "up"
    else:
        direction = "down"
    return abs_d, pct, direction


def _delta_format(abs_d: float, pct: float, direction: str, suffix: str = "") -> str:
    if direction == "flat":
        bg, color, arrow = "#F1EFE8", "#5F5E5A", "≈"
    elif direction == "up":
        bg, color, arrow = "#EAF3DE", "#3B6D11", "↑"
    else:
        bg, color, arrow = "#FCEBEB", "#A32D2D", "↓"
    return (
        f'<span style="background:{bg}; color:{color}; '
        f'padding:3px 8px; border-radius:5px; font-weight:500; font-size:12px; '
        f'font-variant-numeric:tabular-nums;">'
        f'{arrow} {abs_d:+.1f}{suffix} ({pct:+.0f}%)</span>'
    )


def render(
    df: pd.DataFrame,
    *,
    key_prefix: str = "cmp",
    show_title: bool = True,
) -> None:
    """Рендерит UI сравнения двух периодов.

    df — DataFrame активностей; ожидаемые колонки:
      day, activity_type_ru, duration_h, distance_km, activity_id
    key_prefix — префикс session_state и widget-ключей.
    show_title — показывать ли st.title (на отдельной странице да, в tab2 нет).
    """

    K = key_prefix

    # ===== CSS: стилизуем все контейнеры под stExpander из tab1 =====
    # (белый фон, тонкая рамка, скругление 7px, паддинг). Селекторы
    # .st-key-<key> — стабильны (см. memory: feedback_streamlit_css.md).
    st.markdown(
        f'<style>'
        f'.st-key-{K}_period_input_1, .st-key-{K}_period_input_2,'
        f'.st-key-{K}_filter,'
        f'.st-key-{K}_period_card_1, .st-key-{K}_period_card_2,'
        f'.st-key-{K}_result {{'
        f'  background: #FFFFFF !important;'
        f'  border-radius: 7px !important;'
        f'  border: 0.5px solid rgba(0,0,0,0.10) !important;'
        f'  padding: 12px 14px !important;'
        f'  margin-bottom: 8px !important;'
        f'}}'
        f'</style>',
        unsafe_allow_html=True,
    )

    # ===== Шапка + help =====
    if show_title:
        st.title("📊 Сравнение периодов")
    st.markdown(
        '<div style="background:#E6F1FB; color:#185FA5; padding:10px 14px; '
        'border-radius:6px; font-size:12px; line-height:1.5; margin-bottom:14px;">'
        '<b>Как работает:</b> выбери два периода через даты или быстрые шаблоны. '
        'По умолчанию учитываются <b>все виды</b> активности. Для «честного» '
        'сравнения только по конкретным дисциплинам — переключи фильтр на «Выбрать» '
        'и оставь нужные виды.'
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
        st.session_state[f"{K}_filter_mode"] = "Все активности"

    # ===== Helpers для preset =====
    # ВАЖНО: эти callbacks вызываются ЧЕРЕЗ st.button(on_click=...) — они
    # выполняются ДО рендера виджетов на следующем rerun, поэтому могут
    # менять session_state[key], даже если key совпадает с key виджета
    # date_input. Прямой вызов после st.button() приведёт к
    # StreamlitAPIException ("cannot be modified after the widget is
    # instantiated").
    def _apply_preset_p1_days(days: int) -> None:
        today_local = date.today()
        st.session_state[f"{K}_p1_end"] = today_local
        st.session_state[f"{K}_p1_start"] = today_local - timedelta(days=days - 1)

    def _apply_preset_p1_curmonth() -> None:
        today_local = date.today()
        st.session_state[f"{K}_p1_start"] = today_local.replace(day=1)
        st.session_state[f"{K}_p1_end"] = today_local

    def _apply_preset_p2_prev_period() -> None:
        p1_start = st.session_state[f"{K}_p1_start"]
        p1_end = st.session_state[f"{K}_p1_end"]
        p1_len = (p1_end - p1_start).days + 1
        end_d = p1_start - timedelta(days=1)
        start_d = end_d - timedelta(days=p1_len - 1)
        st.session_state[f"{K}_p2_start"] = start_d
        st.session_state[f"{K}_p2_end"] = end_d

    def _apply_preset_p2_year_ago() -> None:
        p1_start = st.session_state[f"{K}_p1_start"]
        p1_end = st.session_state[f"{K}_p1_end"]
        st.session_state[f"{K}_p2_start"] = p1_start - timedelta(days=365)
        st.session_state[f"{K}_p2_end"] = p1_end - timedelta(days=365)

    def _apply_preset_p2_prev_month() -> None:
        today_local = date.today()
        first_of_curr = today_local.replace(day=1)
        end_d = first_of_curr - timedelta(days=1)
        start_d = end_d.replace(day=1)
        st.session_state[f"{K}_p2_start"] = start_d
        st.session_state[f"{K}_p2_end"] = end_d

    # ===== Render Period Input =====
    def _render_period_input(period_num: int, color: str) -> None:
        label = "Период 1 · Основной" if period_num == 1 else "Период 2 · Сравнение"
        key_start = f"{K}_p{period_num}_start"
        key_end = f"{K}_p{period_num}_end"

        with st.container(border=True, key=f"{K}_period_input_{period_num}"):
            st.markdown(
                f'<div style="display:flex; align-items:center; gap:8px; '
                f'font-size:10px; color:#5F5E5A; font-weight:500; '
                f'text-transform:uppercase; letter-spacing:0.5px; margin-bottom:8px;">'
                f'<span style="display:inline-block; width:8px; height:8px; '
                f'border-radius:50%; background:{color};"></span>{label}'
                f'</div>',
                unsafe_allow_html=True,
            )

            # ВАЖНО: один key для виджета и для логики (без value=).
            # Preset-кнопки меняют ss[key_start] / ss[key_end] напрямую —
            # на следующем rerun date_input подхватит новое значение.
            # Если бы мы передавали value=, Streamlit на 2-м рендере
            # игнорирует его и использует внутренний widget state — preset
            # переставал бы работать.
            date_cols = st.columns([2, 1, 2])
            with date_cols[0]:
                st.date_input(
                    "От",
                    key=key_start,
                    label_visibility="collapsed",
                )
            with date_cols[1]:
                st.markdown(
                    '<div style="text-align:center; padding-top:6px; color:#5F5E5A;">→</div>',
                    unsafe_allow_html=True,
                )
            with date_cols[2]:
                st.date_input(
                    "До",
                    key=key_end,
                    label_visibility="collapsed",
                )

            # Presets — используем on_click callbacks (см. комментарий
            # к _apply_preset_p*_*)
            if period_num == 1:
                preset_cols = st.columns(4)
                with preset_cols[0]:
                    st.button(
                        "7 дней",
                        key=f"{K}_p1_preset_7",
                        use_container_width=True,
                        on_click=_apply_preset_p1_days,
                        args=(7,),
                    )
                with preset_cols[1]:
                    st.button(
                        "14 дней",
                        key=f"{K}_p1_preset_14",
                        use_container_width=True,
                        on_click=_apply_preset_p1_days,
                        args=(14,),
                    )
                with preset_cols[2]:
                    st.button(
                        "30 дней",
                        key=f"{K}_p1_preset_30",
                        use_container_width=True,
                        on_click=_apply_preset_p1_days,
                        args=(30,),
                    )
                with preset_cols[3]:
                    st.button(
                        "Текущий месяц",
                        key=f"{K}_p1_preset_curmonth",
                        use_container_width=True,
                        on_click=_apply_preset_p1_curmonth,
                    )
            else:
                preset_cols = st.columns(3)
                with preset_cols[0]:
                    st.button(
                        "Предыдущий равный",
                        key=f"{K}_p2_preset_prev",
                        use_container_width=True,
                        on_click=_apply_preset_p2_prev_period,
                    )
                with preset_cols[1]:
                    st.button(
                        "Год назад",
                        key=f"{K}_p2_preset_year",
                        use_container_width=True,
                        on_click=_apply_preset_p2_year_ago,
                    )
                with preset_cols[2]:
                    st.button(
                        "Прошлый месяц",
                        key=f"{K}_p2_preset_prevmonth",
                        use_container_width=True,
                        on_click=_apply_preset_p2_prev_month,
                    )

            # Meta
            days_count = (
                st.session_state[key_end] - st.session_state[key_start]
            ).days + 1
            if not df.empty:
                mask = (df["day"] >= st.session_state[key_start]) & (
                    df["day"] <= st.session_state[key_end]
                )
                act_count = int(mask.sum())
            else:
                act_count = 0
            st.markdown(
                f'<div style="margin-top:8px; font-size:11px; color:#5F5E5A;">'
                f'<b>{days_count}</b> дней · <b>{act_count}</b> активностей</div>',
                unsafe_allow_html=True,
            )

    # Render two period inputs side-by-side
    period_cols = st.columns(2)
    with period_cols[0]:
        _render_period_input(1, "#185FA5")
    with period_cols[1]:
        _render_period_input(2, "#888780")

    # ===== Activity Filter =====
    def _get_period_sports(start_d: date, end_d: date) -> set:
        if df.empty:
            return set()
        mask = (df["day"] >= start_d) & (df["day"] <= end_d)
        return set(df.loc[mask, "activity_type_ru"].dropna().unique())

    p1_sports = _get_period_sports(
        st.session_state[f"{K}_p1_start"], st.session_state[f"{K}_p1_end"]
    )
    p2_sports = _get_period_sports(
        st.session_state[f"{K}_p2_start"], st.session_state[f"{K}_p2_end"]
    )
    all_available_sports = sorted(p1_sports | p2_sports)

    with st.container(border=True, key=f"{K}_filter"):
        filter_cols = st.columns([3, 2])
        with filter_cols[0]:
            st.markdown(
                '<div style="font-size:13px; font-weight:500; padding-top:6px;">'
                'Активности</div>',
                unsafe_allow_html=True,
            )
        with filter_cols[1]:
            st.segmented_control(
                "Режим",
                ["Все активности", "Выбрать"],
                default=st.session_state.get(f"{K}_filter_mode", "Все активности"),
                selection_mode="single",
                key=f"{K}_filter_mode",
                label_visibility="collapsed",
            )

        mode_choice = (
            st.session_state.get(f"{K}_filter_mode", "Все активности")
            or "Все активности"
        )

        if mode_choice == "Выбрать":
            if not all_available_sports:
                st.info("Нет активностей в выбранных периодах для фильтрации.")
                selected_sports = []
            else:
                _ms_key = (
                    f"{K}_sports_pills_"
                    f"{abs(hash(tuple(all_available_sports)))}"
                )
                selected_sports = st.pills(
                    "Виды спорта",
                    all_available_sports,
                    selection_mode="multi",
                    default=all_available_sports,
                    key=_ms_key,
                    label_visibility="collapsed",
                )
                selected_sports = selected_sports or []
                st.session_state[f"{K}_selected_sports"] = selected_sports
                if not selected_sports:
                    st.markdown(
                        '<div style="background:#FAEEDA; color:#854F0B; padding:6px 10px; '
                        'border-radius:5px; font-size:11px; margin-top:8px;">'
                        '⚠️ Не выбрано ни одной активности — выберите хотя бы один вид'
                        '</div>',
                        unsafe_allow_html=True,
                    )
                else:
                    st.markdown(
                        f'<div style="background:#E6F1FB; color:#185FA5; padding:6px 10px; '
                        f'border-radius:5px; font-size:11px; margin-top:8px;">'
                        f'✓ Выбрано <b>{len(selected_sports)}</b>: '
                        f'{", ".join(selected_sports)}'
                        f'</div>',
                        unsafe_allow_html=True,
                    )
        else:
            # all mode — все виды учитываются
            if all_available_sports:
                st.markdown(
                    f'<div style="opacity:0.5; font-size:12px; padding:6px 0;">'
                    f'{" · ".join(all_available_sports)}'
                    f'</div>',
                    unsafe_allow_html=True,
                )
            selected_sports = list(all_available_sports)
            st.markdown(
                '<div style="background:#E6F1FB; color:#185FA5; padding:6px 10px; '
                'border-radius:5px; font-size:11px; margin-top:8px;">'
                '✓ Учитываются <b>все активности</b>'
                '</div>',
                unsafe_allow_html=True,
            )

    # ===== Compute period data =====
    def _compute_period(start_d: date, end_d: date, sports: list) -> dict:
        if df.empty:
            return {
                "sports": [],
                "totals": {"hours": 0.0, "km": 0.0, "sports_count": 0},
                "days": (end_d - start_d).days + 1,
                "activities_count": 0,
            }
        mask = (df["day"] >= start_d) & (df["day"] <= end_d)
        period_view = df[mask]
        grp = (
            period_view.groupby("activity_type_ru")
            .agg(
                hours=("duration_h", "sum"),
                km=("distance_km", "sum"),
                count=("activity_id", "count"),
            )
            .reset_index()
            .sort_values("hours", ascending=False)
        )
        sports_set = set(sports) if sports else set()
        grp["excluded"] = ~grp["activity_type_ru"].isin(sports_set)
        incl = grp[~grp["excluded"]]
        return {
            "sports": grp.to_dict("records"),
            "totals": {
                "hours": float(incl["hours"].sum()),
                "km": float(incl["km"].sum()),
                "sports_count": int(len(incl)),
            },
            "days": (end_d - start_d).days + 1,
            "activities_count": int(period_view.shape[0]),
        }

    p1 = _compute_period(
        st.session_state[f"{K}_p1_start"],
        st.session_state[f"{K}_p1_end"],
        selected_sports,
    )
    p2 = _compute_period(
        st.session_state[f"{K}_p2_start"],
        st.session_state[f"{K}_p2_end"],
        selected_sports,
    )

    # ===== Период-карточки =====
    def _render_period_card(
        p: dict, label: str, color: str, period_obj: dict, card_num: int,
    ) -> None:
        with st.container(border=True, key=f"{K}_period_card_{card_num}"):
            st.markdown(
                f'<div style="display:flex; align-items:center; gap:8px; '
                f'font-size:10px; color:#5F5E5A; font-weight:500; '
                f'text-transform:uppercase; letter-spacing:0.5px; margin-bottom:6px;">'
                f'<span style="display:inline-block; width:8px; height:8px; '
                f'border-radius:50%; background:{color};"></span>{label}'
                f'</div>',
                unsafe_allow_html=True,
            )
            st.markdown(
                f'<div style="font-size:15px; font-weight:500; line-height:1.2;">'
                f'{_format_period(period_obj["start"], period_obj["end"])}</div>'
                f'<div style="font-size:11px; color:#5F5E5A; margin-bottom:10px;">'
                f'<b>{p["days"]}</b> дней · <b>{p["activities_count"]}</b> активностей</div>',
                unsafe_allow_html=True,
            )
            if not p["sports"]:
                st.markdown(
                    '<div style="font-size:12px; color:#5F5E5A; padding:8px 0;">'
                    'Нет активностей в этом периоде</div>',
                    unsafe_allow_html=True,
                )
            else:
                rows_html = ""
                for s in p["sports"]:
                    opacity = "0.35" if s["excluded"] else "1"
                    td_style = "text-decoration:line-through;" if s["excluded"] else ""
                    rows_html += (
                        f'<div style="display:grid; '
                        f'grid-template-columns:1fr 80px 80px; '
                        f'padding:5px 0; font-size:12px; align-items:center; '
                        f'border-bottom:0.5px solid rgba(0,0,0,0.05); '
                        f'opacity:{opacity}; {td_style}">'
                        f'<span>{s["activity_type_ru"]}</span>'
                        f'<span style="text-align:right; font-variant-numeric:tabular-nums;">'
                        f'{s["hours"]:.1f} ч</span>'
                        f'<span style="text-align:right; font-variant-numeric:tabular-nums;">'
                        f'{s["km"]:.1f} км</span>'
                        f'</div>'
                    )
                st.markdown(rows_html, unsafe_allow_html=True)
            st.markdown(
                f'<div style="display:flex; justify-content:space-between; '
                f'background:#F5F4EF; padding:8px 10px; border-radius:5px; '
                f'margin-top:8px; font-size:13px; font-weight:500;">'
                f'<span>Итого:</span>'
                f'<span style="font-variant-numeric:tabular-nums;">'
                f'{p["totals"]["hours"]:.1f} ч · {p["totals"]["km"]:.1f} км'
                f'</span></div>',
                unsafe_allow_html=True,
            )

    p1_obj = {
        "start": st.session_state[f"{K}_p1_start"],
        "end": st.session_state[f"{K}_p1_end"],
    }
    p2_obj = {
        "start": st.session_state[f"{K}_p2_start"],
        "end": st.session_state[f"{K}_p2_end"],
    }

    card_cols = st.columns(2)
    with card_cols[0]:
        _render_period_card(p1, "Период 1 · Основной", "#185FA5", p1_obj, 1)
    with card_cols[1]:
        _render_period_card(p2, "Период 2 · Сравнение", "#888780", p2_obj, 2)

    # ===== Result Card =====
    with st.container(border=True, key=f"{K}_result"):
        st.markdown(
            '<div style="font-size:14px; font-weight:500; margin-bottom:10px;">'
            '📊 Результат сравнения</div>',
            unsafe_allow_html=True,
        )

        if mode_choice == "Выбрать" and not selected_sports:
            st.info(
                "Выберите хотя бы один вид спорта в фильтре выше, "
                "чтобы построить сравнение."
            )
        else:
            h_abs, h_pct, h_dir = _delta(p1["totals"]["hours"], p2["totals"]["hours"])
            k_abs, k_pct, k_dir = _delta(p1["totals"]["km"], p2["totals"]["km"])
            s_abs, s_pct, s_dir = _delta(
                p1["totals"]["sports_count"], p2["totals"]["sports_count"]
            )

            table_html = (
                '<table style="width:100%; border-collapse:collapse; font-size:13px;">'
                '<thead>'
                '<tr style="border-bottom:0.5px solid rgba(0,0,0,0.15);">'
                '<th style="text-align:left; padding:8px 6px; font-weight:500; '
                'color:#5F5E5A; font-size:11px; text-transform:uppercase; '
                'letter-spacing:0.5px;">Метрика</th>'
                '<th style="text-align:right; padding:8px 6px; font-weight:500; '
                'color:#5F5E5A; font-size:11px; text-transform:uppercase; '
                'letter-spacing:0.5px;">Период 1</th>'
                '<th style="text-align:right; padding:8px 6px; font-weight:500; '
                'color:#5F5E5A; font-size:11px; text-transform:uppercase; '
                'letter-spacing:0.5px;">Период 2</th>'
                '<th style="text-align:right; padding:8px 6px; font-weight:500; '
                'color:#5F5E5A; font-size:11px; text-transform:uppercase; '
                'letter-spacing:0.5px;">Дельта</th>'
                '</tr></thead><tbody>'
                f'<tr style="border-bottom:0.5px solid rgba(0,0,0,0.08);">'
                f'<td style="padding:8px 6px;">Учтено видов</td>'
                f'<td style="text-align:right; padding:8px 6px; '
                f'font-variant-numeric:tabular-nums;">{p1["totals"]["sports_count"]}</td>'
                f'<td style="text-align:right; padding:8px 6px; '
                f'font-variant-numeric:tabular-nums;">{p2["totals"]["sports_count"]}</td>'
                f'<td style="text-align:right; padding:8px 6px;">'
                f'{_delta_format(s_abs, s_pct, s_dir)}</td>'
                f'</tr>'
                f'<tr style="border-bottom:0.5px solid rgba(0,0,0,0.08);">'
                f'<td style="padding:8px 6px;">Часов</td>'
                f'<td style="text-align:right; padding:8px 6px; '
                f'font-variant-numeric:tabular-nums;">{p1["totals"]["hours"]:.1f}</td>'
                f'<td style="text-align:right; padding:8px 6px; '
                f'font-variant-numeric:tabular-nums;">{p2["totals"]["hours"]:.1f}</td>'
                f'<td style="text-align:right; padding:8px 6px;">'
                f'{_delta_format(h_abs, h_pct, h_dir, " ч")}</td>'
                f'</tr>'
                f'<tr>'
                f'<td style="padding:8px 6px;">Километров</td>'
                f'<td style="text-align:right; padding:8px 6px; '
                f'font-variant-numeric:tabular-nums;">{p1["totals"]["km"]:.1f}</td>'
                f'<td style="text-align:right; padding:8px 6px; '
                f'font-variant-numeric:tabular-nums;">{p2["totals"]["km"]:.1f}</td>'
                f'<td style="text-align:right; padding:8px 6px;">'
                f'{_delta_format(k_abs, k_pct, k_dir, " км")}</td>'
                f'</tr>'
                '</tbody></table>'
            )
            st.markdown(table_html, unsafe_allow_html=True)

            # Inline insight
            st.markdown('<div style="margin-top:12px;"></div>', unsafe_allow_html=True)
            if mode_choice == "Все активности":
                only_in_1 = sorted(p1_sports - p2_sports)
                only_in_2 = sorted(p2_sports - p1_sports)
                if not only_in_1 and not only_in_2:
                    st.markdown(
                        '<div style="background:#E6F1FB; color:#185FA5; padding:10px 12px; '
                        'border-radius:5px; font-size:12px; line-height:1.5;">'
                        '✓ Все виды активности присутствуют в обоих периодах. '
                        'Сравнение полностью корректно.'
                        '</div>',
                        unsafe_allow_html=True,
                    )
                else:
                    msg = (
                        '⚠ В периодах есть виды спорта, '
                        'присутствующие только в одном из них.'
                    )
                    if only_in_1:
                        msg += f' <b>Только в П1:</b> {", ".join(only_in_1)}.'
                    if only_in_2:
                        msg += f' <b>Только в П2:</b> {", ".join(only_in_2)}.'
                    msg += (
                        ' Если нужно «честное» сравнение — переключи фильтр на '
                        '«Выбрать» и оставь только общие виды.'
                    )
                    st.markdown(
                        f'<div style="background:#FAEEDA; color:#854F0B; padding:10px 12px; '
                        f'border-radius:5px; font-size:12px; line-height:1.5;">'
                        f'{msg}'
                        f'</div>',
                        unsafe_allow_html=True,
                    )
            elif selected_sports:
                st.markdown(
                    f'<div style="background:#E6F1FB; color:#185FA5; padding:10px 12px; '
                    f'border-radius:5px; font-size:12px; line-height:1.5;">'
                    f'ℹ Сравниваются только выбранные виды активности: '
                    f'<b>{", ".join(selected_sports)}</b>.'
                    f'</div>',
                    unsafe_allow_html=True,
                )
