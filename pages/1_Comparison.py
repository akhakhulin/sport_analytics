"""
Сравнение периодов — отдельная страница multipage app.
Спека: docs/Сравнение периодов/SPECIFICATION_period_comparison.md
"""

from __future__ import annotations

from datetime import date, timedelta
from pathlib import Path

import pandas as pd
import streamlit as st
from dotenv import load_dotenv

load_dotenv()

import auth  # noqa: E402
auth.apply_secrets_to_env()
import db as dbm  # noqa: E402

# === Авторизация (как на главной) ===
USER = auth.require_login()
MY_ATHLETE = USER.athlete_id
IS_ADMIN = USER.role == "coach"

st.set_page_config(
    page_title="Сравнение периодов · Sportsmen Analytics",
    layout="wide",
    page_icon="📊",
    initial_sidebar_state="expanded",
)

# Подключаем общий CSS дашборда
def _inject_dashboard_css() -> None:
    css_path = Path(__file__).parent.parent / "static" / "dashboard.css"
    if css_path.exists():
        st.markdown(
            f"<style>{css_path.read_text(encoding='utf-8')}</style>",
            unsafe_allow_html=True,
        )

_inject_dashboard_css()


# ===== Загрузка данных (минимум для этой страницы) =====
def _read_sql(query: str, params: tuple = ()) -> pd.DataFrame:
    conn = dbm.connect()
    try:
        cur = conn.execute(query, params) if params else conn.execute(query)
        cols = [d[0] for d in cur.description] if cur.description else []
        rows = cur.fetchall()
        return pd.DataFrame(rows, columns=cols)
    finally:
        try:
            conn.close()
        except Exception:
            pass


# Локализация типов активности — копия из dashboard.py (минимум нужного)
ACTIVITY_TYPE_RU = {
    "running": "Бег",
    "indoor_running": "Беговая дорожка",
    "treadmill_running": "Беговая дорожка",
    "trail_running": "Трейл",
    "track_running": "Стадион",
    "virtual_run": "Виртуальный бег",
    "cycling": "Велосипед",
    "indoor_cycling": "Велотренажёр",
    "road_biking": "Шоссейный велосипед",
    "mountain_biking": "Маунтинбайк",
    "gravel_cycling": "Гравел",
    "virtual_ride": "Виртуальная вело",
    "strength_training": "Силовая",
    "cardio": "Кардио",
    "yoga": "Йога",
    "pilates": "Пилатес",
    "lap_swimming": "Бассейн",
    "open_water_swimming": "Открытая вода",
    "swimming": "Плавание",
    "cross_country_skiing": "Лыжи",
    "skate_skiing": "Лыжи · конёк",
    "classic_xc_skiing": "Лыжи · классика",
    "hiking": "Хайкинг",
    "walking": "Ходьба",
    "breathwork": "Дыхательная",
}


def _ru_activity(t: str | None) -> str | None:
    if t is None:
        return None
    return ACTIVITY_TYPE_RU.get(str(t), str(t))


@st.cache_data(ttl=300)
def load_activities(athlete_id: str) -> pd.DataFrame:
    df = _read_sql(
        "SELECT * FROM activities WHERE athlete_id = ?", (athlete_id,)
    )
    if df.empty:
        return df
    df["start"] = pd.to_datetime(df["start_time_local"])
    df["day"] = df["start"].dt.date
    df["activity_type_ru"] = df["activity_type"].apply(_ru_activity)
    df["distance_km"] = df["distance_m"] / 1000
    df["duration_h"] = df["duration_sec"] / 3600
    return df


@st.cache_data(ttl=300)
def _list_athletes() -> list[str]:
    df = _read_sql(
        "SELECT DISTINCT athlete_id FROM activities ORDER BY athlete_id"
    )
    return df["athlete_id"].tolist() if not df.empty else []


# ===== Шапка + help (показываем СРАЗУ, до медленных БД-запросов) =====
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


# ===== Селектор атлета + загрузка данных =====
with st.spinner("Загружаю список атлетов…"):
    all_athletes = _list_athletes() or [MY_ATHLETE]

if IS_ADMIN and len(all_athletes) > 1:
    selected_athlete = st.sidebar.selectbox(
        "👤 Атлет",
        all_athletes,
        index=all_athletes.index(MY_ATHLETE) if MY_ATHLETE in all_athletes else 0,
        key="cmp_athlete_select",
    )
else:
    selected_athlete = MY_ATHLETE
    st.sidebar.markdown(
        f'<div style="font-size:11px; color:#5F5E5A; text-transform:uppercase; '
        f'letter-spacing:0.5px; font-weight:500; margin-bottom:4px;">👤 Атлет</div>'
        f'<div style="font-size:13px;">{selected_athlete}</div>',
        unsafe_allow_html=True,
    )

with st.spinner(f"Загружаю активности атлета {selected_athlete}…"):
    df = load_activities(selected_athlete)


# ===== State init (URL → session_state → defaults) =====
def _read_url_state() -> None:
    """URL params → session_state. Бьёт дефолты, но не пересиливает уже заданное."""
    qp = st.query_params
    for url_key, ss_key in [
        ("p1_start", "cmp_p1_start"),
        ("p1_end", "cmp_p1_end"),
        ("p2_start", "cmp_p2_start"),
        ("p2_end", "cmp_p2_end"),
    ]:
        if url_key in qp and ss_key not in st.session_state:
            try:
                st.session_state[ss_key] = date.fromisoformat(qp[url_key])
            except ValueError:
                pass
    if "filter" in qp and "cmp_filter_mode" not in st.session_state:
        v = qp["filter"]
        if v == "all":
            st.session_state["cmp_filter_mode"] = "Все активности"
        elif v == "custom":
            st.session_state["cmp_filter_mode"] = "Выбрать"
    if "types" in qp and "cmp_url_types" not in st.session_state:
        # Запоминаем, чтобы при первом рендере pills проставить дефолт
        types_raw = qp["types"]
        st.session_state["cmp_url_types"] = [
            t for t in types_raw.split(",") if t
        ]


def _init_state() -> None:
    today = date.today()
    if "cmp_p1_start" not in st.session_state:
        st.session_state["cmp_p1_start"] = today - timedelta(days=13)
    if "cmp_p1_end" not in st.session_state:
        st.session_state["cmp_p1_end"] = today
    if "cmp_p2_start" not in st.session_state:
        st.session_state["cmp_p2_start"] = today - timedelta(days=27)
    if "cmp_p2_end" not in st.session_state:
        st.session_state["cmp_p2_end"] = today - timedelta(days=14)
    if "cmp_filter_mode" not in st.session_state:
        st.session_state["cmp_filter_mode"] = "Все активности"


_read_url_state()
_init_state()


def _write_url_state(mode_choice: str, selected_sports: list) -> None:
    """session_state → URL params (для shareable links)."""
    new_qp = {
        "p1_start": st.session_state["cmp_p1_start"].isoformat(),
        "p1_end": st.session_state["cmp_p1_end"].isoformat(),
        "p2_start": st.session_state["cmp_p2_start"].isoformat(),
        "p2_end": st.session_state["cmp_p2_end"].isoformat(),
        "filter": "custom" if mode_choice == "Выбрать" else "all",
    }
    if mode_choice == "Выбрать" and selected_sports:
        new_qp["types"] = ",".join(selected_sports)
    # Пишем только то, что изменилось — иначе лишний rerun
    current = dict(st.query_params)
    # Удалить ключ types если он есть в URL, но не должен быть
    if "types" not in new_qp and "types" in current:
        del st.query_params["types"]
        current = dict(st.query_params)
    if {k: current.get(k) for k in new_qp} != new_qp:
        st.query_params.from_dict(new_qp)


# ===== Helpers для preset =====
def _apply_preset_p1(preset_type: str, days: int | None = None) -> None:
    today = date.today()
    if preset_type == "days_back":
        st.session_state["cmp_p1_end"] = today
        st.session_state["cmp_p1_start"] = today - timedelta(days=days - 1)
    elif preset_type == "current_month":
        st.session_state["cmp_p1_start"] = today.replace(day=1)
        st.session_state["cmp_p1_end"] = today


def _apply_preset_p2(preset_type: str) -> None:
    today = date.today()
    p1_start = st.session_state["cmp_p1_start"]
    p1_end = st.session_state["cmp_p1_end"]
    p1_len = (p1_end - p1_start).days + 1
    if preset_type == "previous_period":
        end = p1_start - timedelta(days=1)
        start = end - timedelta(days=p1_len - 1)
        st.session_state["cmp_p2_start"] = start
        st.session_state["cmp_p2_end"] = end
    elif preset_type == "year_ago":
        st.session_state["cmp_p2_start"] = p1_start - timedelta(days=365)
        st.session_state["cmp_p2_end"] = p1_end - timedelta(days=365)
    elif preset_type == "previous_month":
        first_of_curr = today.replace(day=1)
        end = first_of_curr - timedelta(days=1)
        start = end.replace(day=1)
        st.session_state["cmp_p2_start"] = start
        st.session_state["cmp_p2_end"] = end


# ===== Render Period Input =====
def _render_period_input(period_num: int, color: str) -> None:
    label = "Период 1 · Основной" if period_num == 1 else "Период 2 · Сравнение"
    key_start = f"cmp_p{period_num}_start"
    key_end = f"cmp_p{period_num}_end"

    with st.container(border=True):
        st.markdown(
            f'<div style="display:flex; align-items:center; gap:8px; '
            f'font-size:10px; color:#5F5E5A; font-weight:500; '
            f'text-transform:uppercase; letter-spacing:0.5px; margin-bottom:8px;">'
            f'<span style="display:inline-block; width:8px; height:8px; '
            f'border-radius:50%; background:{color};"></span>{label}'
            f'</div>',
            unsafe_allow_html=True,
        )

        date_cols = st.columns([2, 1, 2])
        with date_cols[0]:
            start = st.date_input(
                "От",
                value=st.session_state[key_start],
                key=f"{key_start}_input",
                label_visibility="collapsed",
            )
        with date_cols[1]:
            st.markdown(
                '<div style="text-align:center; padding-top:6px; color:#5F5E5A;">→</div>',
                unsafe_allow_html=True,
            )
        with date_cols[2]:
            end = st.date_input(
                "До",
                value=st.session_state[key_end],
                key=f"{key_end}_input",
                label_visibility="collapsed",
            )
        # Sync state из date_input
        if start != st.session_state[key_start]:
            st.session_state[key_start] = start
        if end != st.session_state[key_end]:
            st.session_state[key_end] = end

        # Presets
        if period_num == 1:
            preset_cols = st.columns(4)
            with preset_cols[0]:
                if st.button("7 дней", key="p1_preset_7", use_container_width=True):
                    _apply_preset_p1("days_back", 7)
                    st.rerun()
            with preset_cols[1]:
                if st.button("14 дней", key="p1_preset_14", use_container_width=True):
                    _apply_preset_p1("days_back", 14)
                    st.rerun()
            with preset_cols[2]:
                if st.button("30 дней", key="p1_preset_30", use_container_width=True):
                    _apply_preset_p1("days_back", 30)
                    st.rerun()
            with preset_cols[3]:
                if st.button(
                    "Текущий месяц",
                    key="p1_preset_curmonth",
                    use_container_width=True,
                ):
                    _apply_preset_p1("current_month")
                    st.rerun()
        else:
            preset_cols = st.columns(3)
            with preset_cols[0]:
                if st.button(
                    "Предыдущий равный",
                    key="p2_preset_prev",
                    use_container_width=True,
                ):
                    _apply_preset_p2("previous_period")
                    st.rerun()
            with preset_cols[1]:
                if st.button(
                    "Год назад", key="p2_preset_year", use_container_width=True
                ):
                    _apply_preset_p2("year_ago")
                    st.rerun()
            with preset_cols[2]:
                if st.button(
                    "Прошлый месяц",
                    key="p2_preset_prevmonth",
                    use_container_width=True,
                ):
                    _apply_preset_p2("previous_month")
                    st.rerun()

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


# ===== Валидация периодов =====
def _validate_periods() -> tuple[list[str], list[str]]:
    today = date.today()
    p1s = st.session_state["cmp_p1_start"]
    p1e = st.session_state["cmp_p1_end"]
    p2s = st.session_state["cmp_p2_start"]
    p2e = st.session_state["cmp_p2_end"]
    errors: list[str] = []
    warnings: list[str] = []

    # Фатальные: end < start
    if p1e < p1s:
        errors.append(
            "Период 1: дата конца раньше начала — поправь даты."
        )
    if p2e < p2s:
        errors.append(
            "Период 2: дата конца раньше начала — поправь даты."
        )
    # Фатальные: целиком в будущем
    if p1s > today:
        errors.append("Период 1 целиком в будущем — данных нет.")
    if p2s > today:
        errors.append("Период 2 целиком в будущем — данных нет.")

    if errors:
        return errors, warnings

    # Нефатальные: > 365 дней
    if (p1e - p1s).days + 1 > 365:
        warnings.append(
            "Период 1 длиннее года — расчёт может занять заметно больше."
        )
    if (p2e - p2s).days + 1 > 365:
        warnings.append(
            "Период 2 длиннее года — расчёт может занять заметно больше."
        )

    # Нефатальные: пересечение (учитываем только если обе даты валидны)
    overlap_start = max(p1s, p2s)
    overlap_end = min(p1e, p2e)
    overlap_days = (overlap_end - overlap_start).days + 1
    if overlap_days > 0:
        warnings.append(
            f"Периоды пересекаются на <b>{overlap_days}</b> "
            f"{'день' if overlap_days == 1 else 'дней'} — это может искажать дельту."
        )

    return errors, warnings


_errors, _warnings = _validate_periods()
for _e in _errors:
    st.error(_e)
for _w in _warnings:
    st.markdown(
        f'<div style="background:#FAEEDA; color:#854F0B; padding:8px 12px; '
        f'border-radius:5px; font-size:12px; line-height:1.5; margin:4px 0;">'
        f'⚠ {_w}</div>',
        unsafe_allow_html=True,
    )
if _errors:
    st.stop()


# ===== Activity Filter =====
def _get_period_sports(start: date, end: date) -> set:
    if df.empty:
        return set()
    mask = (df["day"] >= start) & (df["day"] <= end)
    return set(df.loc[mask, "activity_type_ru"].dropna().unique())


p1_sports = _get_period_sports(
    st.session_state["cmp_p1_start"], st.session_state["cmp_p1_end"]
)
p2_sports = _get_period_sports(
    st.session_state["cmp_p2_start"], st.session_state["cmp_p2_end"]
)
all_available_sports = sorted(p1_sports | p2_sports)

with st.container(border=True):
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
            default=st.session_state.get("cmp_filter_mode", "Все активности"),
            selection_mode="single",
            key="cmp_filter_mode",
            label_visibility="collapsed",
        )

    mode_choice = (
        st.session_state.get("cmp_filter_mode", "Все активности")
        or "Все активности"
    )

    if mode_choice == "Выбрать":
        if not all_available_sports:
            st.info("Нет активностей в выбранных периодах для фильтрации.")
            selected_sports = []
        else:
            # Default: URL types > сохранённый выбор > все доступные
            default_sports = list(all_available_sports)
            if "cmp_url_types" in st.session_state:
                url_t = st.session_state.pop("cmp_url_types")
                cand = [s for s in url_t if s in all_available_sports]
                if cand:
                    default_sports = cand
            elif "cmp_selected_sports" in st.session_state:
                prev_t = st.session_state["cmp_selected_sports"]
                cand = [s for s in prev_t if s in all_available_sports]
                if cand:
                    default_sports = cand

            _ms_key = (
                f"cmp_sports_pills_"
                f"{abs(hash(tuple(all_available_sports)))}"
            )
            selected_sports = st.pills(
                "Виды спорта",
                all_available_sports,
                selection_mode="multi",
                default=default_sports,
                key=_ms_key,
                label_visibility="collapsed",
            )
            selected_sports = selected_sports or []
            st.session_state["cmp_selected_sports"] = selected_sports
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
        # all mode — пилюли приглушены, клик = переход в "Выбрать" с текущим выбором
        if not all_available_sports:
            selected_sports = []
        else:
            # CSS opacity для контейнера пилюль (через .st-key-<key>)
            st.markdown(
                '<style>'
                '.st-key-cmp_pills_dim_wrap [data-baseweb="button"]'
                '{opacity:0.55;}'
                '.st-key-cmp_pills_dim_wrap [data-baseweb="button"]:hover'
                '{opacity:1;}'
                '</style>',
                unsafe_allow_html=True,
            )
            with st.container(key="cmp_pills_dim_wrap"):
                _ms_key_all = (
                    f"cmp_sports_pills_all_"
                    f"{abs(hash(tuple(all_available_sports)))}"
                )
                pills_value = st.pills(
                    "Виды спорта (все учитываются)",
                    all_available_sports,
                    selection_mode="multi",
                    default=all_available_sports,
                    key=_ms_key_all,
                    label_visibility="collapsed",
                )
            # Авто-переключение: пользователь снял какую-то пилюлю → custom
            if pills_value is not None and set(pills_value) != set(
                all_available_sports
            ):
                st.session_state["cmp_filter_mode"] = "Выбрать"
                st.session_state["cmp_selected_sports"] = list(pills_value)
                st.rerun()
            selected_sports = list(all_available_sports)

        st.markdown(
            '<div style="background:#E6F1FB; color:#185FA5; padding:6px 10px; '
            'border-radius:5px; font-size:11px; margin-top:8px;">'
            '✓ Учитываются <b>все активности</b>'
            '</div>',
            unsafe_allow_html=True,
        )


# ===== Compute period data =====
def _compute_period(start: date, end: date, sports: list) -> dict:
    if df.empty:
        return {
            "sports": [],
            "totals": {"hours": 0.0, "km": 0.0, "sports_count": 0},
            "days": (end - start).days + 1,
            "activities_count": 0,
        }
    mask = (df["day"] >= start) & (df["day"] <= end)
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
        "days": (end - start).days + 1,
        "activities_count": int(period_view.shape[0]),
    }


p1 = _compute_period(
    st.session_state["cmp_p1_start"],
    st.session_state["cmp_p1_end"],
    selected_sports,
)
p2 = _compute_period(
    st.session_state["cmp_p2_start"],
    st.session_state["cmp_p2_end"],
    selected_sports,
)


# ===== Период-карточки =====
def _format_period(start: date, end: date) -> str:
    months_ru = {
        1: "янв", 2: "фев", 3: "мар", 4: "апр", 5: "мая", 6: "июн",
        7: "июл", 8: "авг", 9: "сен", 10: "окт", 11: "ноя", 12: "дек",
    }
    if start.year == end.year:
        return (
            f'{start.day} {months_ru[start.month]} – '
            f'{end.day} {months_ru[end.month]} {end.year}'
        )
    return (
        f'{start.day} {months_ru[start.month]} {start.year} – '
        f'{end.day} {months_ru[end.month]} {end.year}'
    )


def _render_period_card(p: dict, label: str, color: str, period_obj: dict) -> None:
    with st.container(border=True):
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
                    f'grid-template-columns:minmax(0,1fr) max-content max-content; '
                    f'gap:10px; padding:5px 0; font-size:12px; '
                    f'align-items:center; '
                    f'border-bottom:0.5px solid rgba(0,0,0,0.05); '
                    f'opacity:{opacity}; {td_style}">'
                    f'<span style="overflow:hidden; text-overflow:ellipsis; '
                    f'white-space:nowrap;">{s["activity_type_ru"]}</span>'
                    f'<span style="text-align:right; white-space:nowrap; '
                    f'font-variant-numeric:tabular-nums;">'
                    f'{s["hours"]:.1f} ч</span>'
                    f'<span style="text-align:right; white-space:nowrap; '
                    f'font-variant-numeric:tabular-nums;">'
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
    "start": st.session_state["cmp_p1_start"],
    "end": st.session_state["cmp_p1_end"],
}
p2_obj = {
    "start": st.session_state["cmp_p2_start"],
    "end": st.session_state["cmp_p2_end"],
}

card_cols = st.columns(2)
with card_cols[0]:
    _render_period_card(p1, "Период 1 · Основной", "#185FA5", p1_obj)
with card_cols[1]:
    _render_period_card(p2, "Период 2 · Сравнение", "#888780", p2_obj)


# ===== Result Card =====
def _delta(v1: float, v2: float) -> tuple:
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


with st.container(border=True):
    st.markdown(
        '<div style="font-size:14px; font-weight:500; margin-bottom:10px;">'
        '📊 Результат сравнения</div>',
        unsafe_allow_html=True,
    )

    # Empty state: фильтр пустой
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


# ===== Sync state → URL (для shareable links) =====
_write_url_state(mode_choice, selected_sports)
