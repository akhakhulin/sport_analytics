"""
Streamlit-дашборд по Garmin-данным.
Запуск: streamlit run dashboard.py
"""

from __future__ import annotations

import json
import os
from datetime import date, datetime, timedelta
from pathlib import Path

import pandas as pd
import plotly.express as px
import plotly.graph_objects as go
from plotly.subplots import make_subplots
import streamlit as st
from dotenv import load_dotenv

load_dotenv()

import auth  # noqa: E402  — должен подгрузиться до db, чтобы перенести Turso-секреты в env
auth.apply_secrets_to_env()

import db as dbm  # noqa: E402

DB_PATH = os.getenv("DB_PATH", "./data/garmin.db")

# Аутентификация. На локальном запуске без st.secrets — fallback на ENV.
USER = auth.require_login()
MY_ATHLETE = USER.athlete_id
IS_ADMIN = USER.role == "coach"

ZONE_COLORS = {
    "Z1": "#8fd694",  # лёгкая
    "Z2": "#4dbd74",  # аэробная база
    "Z3": "#f0c419",  # темповая
    "Z4": "#f39c12",  # порог
    "Z5": "#e74c3c",  # максимальная
}
ZONE_NAMES = {
    "Z1": "Z1 · Разминка",
    "Z2": "Z2 · Аэробная",
    "Z3": "Z3 · Темповая",
    "Z4": "Z4 · Порог",
    "Z5": "Z5 · Максимум",
}


def fmt_dur(hours):
    """<1 ч → минуты, иначе часы с десятой."""
    try:
        h = float(hours)
    except (TypeError, ValueError):
        return ""
    if h <= 0:
        return ""
    if h < 1:
        mins = int(round(h * 60))
        return f"{mins} мин" if mins > 0 else ""
    return f"{h:.1f} ч"


def fmt_hm(hours):
    """Часы:минуты в виде «N ч NN мин» / «N ч» / «NN мин»."""
    try:
        h = float(hours)
    except (TypeError, ValueError):
        return "0"
    if h <= 0:
        return "0"
    total_min = int(round(h * 60))
    if total_min < 60:
        return f"{total_min} мин"
    hh = total_min // 60
    mm = total_min % 60
    return f"{hh} ч {mm:02d} мин" if mm else f"{hh} ч"

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
    "meditation": "Медитация",
    "breathwork": "Дыхательная",
    "stretching": "Растяжка",
    "cross_country_skiing_ws": "Лыжи · классика",
    "skate_skiing_ws": "Лыжи · конёк",
    "backcountry_skiing": "Бэккантри",
    "resort_skiing_snowboarding_ws": "Горные лыжи",
    "snowshoeing_ws": "Снегоступы",
    "lap_swimming": "Бассейн",
    "open_water_swimming": "Открытая вода",
    "swimming": "Плавание",
    "hiking": "Поход",
    "walking": "Ходьба",
    "rowing": "Гребля",
    "indoor_rowing": "Гребной тренажёр",
    "elliptical": "Эллипсоид",
    "stair_climbing": "Степпер",
    "tennis": "Теннис",
    "soccer": "Футбол",
    "basketball": "Баскетбол",
    "fitness_equipment": "Кардио-тренажёр",
}


PLOTLY_CONFIG = {"displayModeBar": False}


@st.dialog(" ", width="large")
def _zoom_dialog(fig_dict: dict, title: str = "") -> None:
    """Открывает график в большом модальном окне (~80% экрана)."""
    fig = go.Figure(fig_dict)
    fig.update_layout(height=720, title=title or fig.layout.title.text or "")
    st.plotly_chart(fig, use_container_width=True, config=PLOTLY_CONFIG)


@st.dialog(" ", width="large")
def _zone_period_dialog(title: str, vals: list[float],
                        zone_names_short: list[str],
                        default_mode: str = "Часы") -> None:
    """Большая модалка для одной строки сетки HR-зон с переключателем
    Часы/Проценты. Подстраивается под ширину окна (60–80% на ПК,
    почти полная на мобильном)."""
    st.markdown(f"### {title}")
    mode = st.radio(
        "Единицы",
        ["Часы", "Проценты"],
        index=0 if default_mode == "Часы" else 1,
        horizontal=True,
        label_visibility="collapsed",
        key=f"zone_dialog_mode_{title}",
    )

    tot = sum(vals) or 1
    pcts = [v / tot * 100 for v in vals]
    dur_text = [fmt_dur(v) for v in vals]

    if mode == "Проценты":
        y_vals = pcts
        text = [f"{p:.0f}%" if p > 0 else "" for p in pcts]
        y_title = "%"
        hover = "%{x}: %{y:.0f}%<br>%{customdata}<extra></extra>"
    else:
        y_vals = vals
        text = dur_text
        y_title = "часов"
        hover = "%{x}: %{customdata}<extra></extra>"

    fig = go.Figure(
        go.Bar(
            x=zone_names_short,
            y=y_vals,
            marker=dict(color=[ZONE_COLORS[z] for z in zone_names_short]),
            text=text,
            textposition="outside",
            cliponaxis=False,
            customdata=dur_text,
            hovertemplate=hover,
        )
    )
    fig.update_layout(
        height=460,
        showlegend=False,
        xaxis=dict(title="", tickangle=0, fixedrange=True),
        yaxis=dict(title=y_title, rangemode="tozero", fixedrange=True),
        margin=dict(t=20, b=30, l=40, r=10),
    )
    st.plotly_chart(fig, use_container_width=True, config=PLOTLY_CONFIG)
    st.caption(f"Всего: **{fmt_dur(sum(vals))}**")


def show_chart(fig, key: str, height: int | None = None, expandable: bool = True) -> None:
    """Рендер графика + значок 🔍 под ним (открывает модалку)."""
    if height is not None:
        fig.update_layout(height=height)
    st.plotly_chart(fig, use_container_width=True, key=f"chart_{key}",
                    config=PLOTLY_CONFIG)
    if expandable:
        if st.button("🔍", key=f"zoom_btn_{key}"):
            _zoom_dialog(fig.to_dict(), title=fig.layout.title.text or "")


def ru_activity(t: str | None) -> str:
    if t is None:
        return "—"
    return ACTIVITY_TYPE_RU.get(t, t.replace("_", " ").capitalize())


def _is_roller_season(d) -> bool:
    """С 1 мая по 15 ноября включительно — летний сезон, лыжные активности
    в это время = лыжероллеры."""
    if d is None or pd.isna(d):
        return False
    m, day = d.month, d.day
    if m in (5, 6, 7, 8, 9, 10):
        return True
    if m == 11 and day <= 15:
        return True
    return False


def ru_activity_seasonal(activity_type: str | None, start_dt) -> str:
    """Перевод с учётом сезона: летние лыжные тренировки → лыжероллеры."""
    if activity_type == "skate_skiing_ws":
        return "Лыжероллеры · конёк" if _is_roller_season(start_dt) else "Лыжи · конёк"
    if activity_type == "cross_country_skiing_ws":
        return "Лыжероллеры · классика" if _is_roller_season(start_dt) else "Лыжи · классика"
    return ru_activity(activity_type)

st.set_page_config(
    page_title="Sportsmen Analytics",
    layout="wide",
    page_icon="🏃",
    initial_sidebar_state="expanded",
)


# Подключаем общий файл стилей (рестайл под прототип)
def _inject_dashboard_css() -> None:
    css_path = Path(__file__).parent / "static" / "dashboard.css"
    if css_path.exists():
        st.markdown(
            f"<style>{css_path.read_text(encoding='utf-8')}</style>",
            unsafe_allow_html=True,
        )


_inject_dashboard_css()


# region Загрузка


def _read_sql(query: str, params: tuple = ()) -> pd.DataFrame:
    """libsql Connection совместим с DB-API, но pandas иногда ругается —
    проще сделать выборку курсором и собрать DataFrame руками."""
    conn = dbm.connect()
    try:
        cur = conn.execute(query, params) if params else conn.execute(query)
        cols = [d[0] for d in cur.description] if cur.description else []
        rows = cur.fetchall()
        return pd.DataFrame(rows, columns=cols) if cols else pd.DataFrame()
    finally:
        conn.close()


@st.cache_data(ttl=300)
def list_athletes() -> list[str]:
    try:
        df = _read_sql("SELECT DISTINCT athlete_id FROM activities ORDER BY athlete_id")
    except Exception as exc:
        # Таблицы ещё нет (Turso пустой) или соединение не настроено
        st.error(
            f"Не получилось прочитать список атлетов из БД.\n\n"
            f"Backend: **{dbm.info()}**\n\n"
            f"Деталь: `{exc}`\n\n"
            "Проверь:\n"
            "- В Streamlit Secrets есть блок `[turso]` с `url` и `token`\n"
            "- Локальный `sync.exe` уже хоть раз клал данные в Turso "
            "(на Cloud-деплое таблицы создаются только при синке, "
            "не при чтении)"
        )
        st.stop()
    return df["athlete_id"].tolist() if not df.empty else []


@st.cache_data(ttl=300)
def load_user_profile(athlete_id: str) -> dict | None:
    try:
        df = _read_sql(
            "SELECT * FROM user_profile WHERE athlete_id = ?", (athlete_id,)
        )
    except Exception:
        return None
    if df.empty:
        return None
    return df.iloc[0].to_dict()


@st.cache_data(ttl=300)
def load_hr_zones(athlete_id: str) -> pd.DataFrame:
    try:
        df = _read_sql(
            "SELECT sport, zone1_floor, zone2_floor, zone3_floor, zone4_floor, "
            "zone5_floor, max_hr, resting_hr, lthr, training_method "
            "FROM hr_zones WHERE athlete_id = ? "
            "ORDER BY CASE sport WHEN 'DEFAULT' THEN 0 WHEN 'RUNNING' THEN 1 "
            "WHEN 'CYCLING' THEN 2 ELSE 3 END",
            (athlete_id,),
        )
    except Exception:
        return pd.DataFrame()
    return df


@st.cache_data(ttl=300)
def load_activities(athlete_id: str) -> pd.DataFrame:
    df = _read_sql(
        "SELECT * FROM activities WHERE athlete_id = ?", (athlete_id,)
    )
    if df.empty:
        return df

    df["start"] = pd.to_datetime(df["start_time_local"])
    df["day"] = df["start"].dt.date
    df["week"] = df["start"].dt.to_period("W").dt.start_time
    df["month"] = df["start"].dt.to_period("M").dt.start_time
    df["year"] = df["start"].dt.to_period("Y").dt.start_time
    df["activity_type_ru"] = [
        ru_activity_seasonal(t, d) for t, d in zip(df["activity_type"], df["start"])
    ]
    df["distance_km"] = df["distance_m"] / 1000
    df["duration_min"] = df["duration_sec"] / 60
    df["duration_h"] = df["duration_sec"] / 3600

    for i in range(1, 6):
        df[f"z{i}_sec"] = df["raw_json"].apply(
            lambda raw, k=f"hrTimeInZone_{i}": (json.loads(raw).get(k) or 0)
        )
    df["hr_zone_total_sec"] = df[[f"z{i}_sec" for i in range(1, 6)]].sum(axis=1)

    # Дозаполнение зон по avg_hr — для активностей где HR писался, но Garmin не разложил
    # время по зонам полностью (типично для силовых: avg_hr есть, hrTimeInZone_* нулевые/частичные).
    # Берём DEFAULT-зоны атлета и относим недостающее время в зону по avg_hr.
    _z = _read_sql(
        "SELECT zone1_floor, zone2_floor, zone3_floor, zone4_floor, zone5_floor "
        "FROM hr_zones WHERE athlete_id = ? AND sport = 'DEFAULT' LIMIT 1",
        (athlete_id,),
    )
    if not _z.empty:
        z1_f, z2_f, z3_f, z4_f, z5_f = (
            int(_z.iloc[0]["zone1_floor"]), int(_z.iloc[0]["zone2_floor"]),
            int(_z.iloc[0]["zone3_floor"]), int(_z.iloc[0]["zone4_floor"]),
            int(_z.iloc[0]["zone5_floor"]),
        )

        def _zone_for_hr(hr: float) -> int:
            if hr >= z5_f: return 5
            if hr >= z4_f: return 4
            if hr >= z3_f: return 3
            if hr >= z2_f: return 2
            return 1  # включая <z1_f — относим в Z1, всё равно низкая нагрузка

        gap = (df["duration_sec"].fillna(0) - df["hr_zone_total_sec"]).clip(lower=0)
        has_hr = df["avg_hr"].notna() & (df["avg_hr"] > 0)
        mask_fill = has_hr & (gap > 1)
        if mask_fill.any():
            zones_idx = df.loc[mask_fill, "avg_hr"].apply(_zone_for_hr)
            for i in range(1, 6):
                sub = mask_fill & (zones_idx.reindex(df.index, fill_value=0) == i)
                df.loc[sub, f"z{i}_sec"] = df.loc[sub, f"z{i}_sec"] + gap.loc[sub]
            df["hr_zone_total_sec"] = df[[f"z{i}_sec" for i in range(1, 6)]].sum(axis=1)
    return df


def compute_pmc(activities_df: pd.DataFrame, lthr: float) -> pd.DataFrame:
    """
    Performance Management Chart: дневной TSS, CTL (фитнес 42д), ATL (усталость 7д), TSB (форма).
    hrTSS по Friel: (sec * IF^2) / 3600 * 100, где IF = avgHR / LTHR.
    """
    if activities_df.empty or lthr <= 0:
        return pd.DataFrame()

    src = activities_df.dropna(subset=["avg_hr", "duration_sec"]).copy()
    if src.empty:
        return pd.DataFrame()

    src["IF"] = src["avg_hr"] / lthr
    src["hrTSS"] = (src["duration_sec"] * src["IF"] ** 2) / 3600 * 100
    src["day"] = pd.to_datetime(src["start_time_local"]).dt.date

    daily_tss = src.groupby("day")["hrTSS"].sum()

    # Пустые дни = 0, чтобы EMA корректно затухала
    full_idx = pd.date_range(daily_tss.index.min(), date.today(), freq="D").date
    pmc = daily_tss.reindex(full_idx, fill_value=0.0).rename("tss").to_frame()
    pmc.index.name = "day"
    pmc = pmc.reset_index()

    pmc["CTL"] = pmc["tss"].ewm(alpha=1 / 42, adjust=False).mean()
    pmc["ATL"] = pmc["tss"].ewm(alpha=1 / 7, adjust=False).mean()
    pmc["TSB"] = pmc["CTL"] - pmc["ATL"]
    return pmc


@st.cache_data(ttl=300)
def load_daily(athlete_id: str) -> pd.DataFrame:
    try:
        daily = _read_sql("SELECT * FROM daily_stats WHERE athlete_id = ?", (athlete_id,))
        sleep = _read_sql("SELECT * FROM sleep WHERE athlete_id = ?", (athlete_id,))
        hrv = _read_sql("SELECT * FROM hrv WHERE athlete_id = ?", (athlete_id,))
    except Exception:
        return pd.DataFrame()
    if daily.empty:
        return daily
    daily["day"] = pd.to_datetime(daily["day"]).dt.date
    if not sleep.empty:
        sleep["day"] = pd.to_datetime(sleep["day"]).dt.date
        sleep["sleep_h"] = sleep["total_sec"] / 3600
        daily = daily.merge(
            sleep[["day", "sleep_h", "sleep_score"]], on="day", how="left"
        )
    if not hrv.empty:
        hrv["day"] = pd.to_datetime(hrv["day"]).dt.date
        daily = daily.merge(
            hrv[["day", "last_night_avg", "weekly_avg"]].rename(
                columns={"last_night_avg": "hrv_night", "weekly_avg": "hrv_week"}
            ),
            on="day",
            how="left",
        )
    return daily


# endregion


# region Sidebar

st.sidebar.markdown(
    f"👋 **{USER.name}**"
    + ("  ·  _тренер_" if IS_ADMIN else "")
)
auth.logout_button()

# Селектор атлета: тренер видит подмножество (или всех), обычный — только себя
all_athletes = list_athletes()
if IS_ADMIN and all_athletes:
    # Если у coach задан visible_athletes — фильтруем дропдаун
    if USER.visible_athletes:
        scoped = [a for a in all_athletes if a in USER.visible_athletes]
        # Если по фильтру никого нет — показываем хотя бы свой athlete_id
        all_athletes = scoped or [MY_ATHLETE]
    default_idx = all_athletes.index(MY_ATHLETE) if MY_ATHLETE in all_athletes else 0
    selected_athlete = st.sidebar.selectbox(
        "👤 Атлет",
        all_athletes,
        index=default_idx,
        help="Выберите атлета",
    )
else:
    selected_athlete = MY_ATHLETE
    # Атлет видит только себя — селекторы не показываем, но сам label оставляем
    st.sidebar.markdown(
        f'<div style="font-size:var(--fs-xs); text-transform:uppercase; '
        f'letter-spacing:0.5px; color:var(--color-text-secondary); '
        f'font-weight:500; margin:8px 0 4px 0;">👤 Атлет</div>'
        f'<div style="font-size:12px; padding:4px 0;">{selected_athlete}</div>',
        unsafe_allow_html=True,
    )

df = load_activities(selected_athlete)
daily = load_daily(selected_athlete)

if df.empty:
    st.error(
        f"Нет данных для атлета **{selected_athlete}**. "
        f"Запусти sync.cmd с правильным ATHLETE_ID в .env."
    )
    st.stop()

min_day = df["day"].min()
max_day = df["day"].max()

st.sidebar.header("Фильтры")

# 2a. Период — добавлен 14d со ★, дефолт = 14d
PERIOD_OPTIONS = ["7 дней", "14 дней ★", "30 дней", "90 дней", "365 дней", "Свой диапазон"]
PERIOD_DAYS = {"7 дней": 7, "14 дней ★": 14, "30 дней": 30, "90 дней": 90, "365 дней": 365}

preset = st.sidebar.radio(
    "Период",
    PERIOD_OPTIONS,
    index=1,  # 14 дней — рекомендованный дефолт
)
if preset == "Свой диапазон":
    picked = st.sidebar.date_input(
        "Диапазон",
        (max_day - timedelta(days=90), max_day),
        help="Если не выбрать конец — возьмётся сегодня",
    )
    if isinstance(picked, (tuple, list)):
        start = picked[0] if len(picked) >= 1 else max_day - timedelta(days=90)
        end = picked[1] if len(picked) >= 2 else date.today()
    else:
        start = picked
        end = date.today()
else:
    end = max_day
    start = end - timedelta(days=PERIOD_DAYS[preset])

# 2b. Типы активности — pills (4 фиксированные группы) + «+ ещё» под expander.
# Группы покрывают самые частые виды; всё остальное идёт в «+ ещё».
PILL_GROUPS = {
    "🏃 Бег": ["Бег", "Беговая дорожка", "Трейл", "Стадион", "Виртуальный бег"],
    "🚴 Велик": ["Велосипед", "Велотренажёр", "Шоссейный велосипед",
                  "Маунтинбайк", "Гравел", "Виртуальная вело"],
    "🏊 Плав.": ["Бассейн", "Открытая вода", "Плавание"],
    "💪 Сила": ["Силовая"],
}
# Учитываем только активности, попавшие в выбранный период
_types_period_mask = (df["day"] >= start) & (df["day"] <= end)
types_all_list = sorted(df.loc[_types_period_mask, "activity_type_ru"].dropna().unique().tolist())
in_pills = {t for vs in PILL_GROUPS.values() for t in vs}
extra_types = [t for t in types_all_list if t not in in_pills]


def _activity_material_icon(t: str) -> str:
    """Material Icons-метка перед именем типа активности.
    Streamlit рендерит «:material/icon_name:» как векторную иконку Material Symbols.
    Для единообразия с другими местами дашборда (drilldown'ы, side-table)."""
    if not isinstance(t, str):
        return t
    tl = t.lower()
    if "конёк" in tl or "конек" in tl:
        return f":material/cross_country_skiing: {t}"
    if "классика" in tl:
        return f":material/downhill_skiing: {t}"
    if t.startswith("Лыжи"):
        return f":material/downhill_skiing: {t}"
    if t.startswith("Лыжероллеры"):
        return f":material/cross_country_skiing: {t}"
    if t in ("Силовая",):
        return f":material/fitness_center: {t}"
    if t in ("Беговая дорожка", "Виртуальный бег"):
        return f":material/directions_run: {t}"
    if t.startswith("Бег") or t in ("Трейл", "Стадион"):
        return f":material/directions_run: {t}"
    if t in ("Велотренажёр", "Виртуальная вело"):
        return f":material/directions_bike: {t}"
    if "велосипед" in tl or "вело" in tl or "маунтин" in tl or "гравел" in tl:
        return f":material/directions_bike: {t}"
    if t in ("Бассейн", "Открытая вода", "Плавание"):
        return f":material/pool: {t}"
    if t in ("Йога", "Пилатес"):
        return f":material/self_improvement: {t}"
    if t in ("Хайкинг",):
        return f":material/hiking: {t}"
    if t in ("Ходьба",):
        return f":material/directions_walk: {t}"
    return t


_PILL_GROUP_LABELS = {
    "🏃 Бег": ":material/directions_run: Бег",
    "🚴 Велик": ":material/directions_bike: Велик",
    "🏊 Плав.": ":material/pool: Плав.",
    "💪 Сила": ":material/fitness_center: Сила",
}


def _pill_group_label(key: str) -> str:
    return _PILL_GROUP_LABELS.get(key, key)

with st.sidebar.container(border=True, key="sa_activity_tile"):
    selected_pills = st.pills(
        "Активность",
        list(PILL_GROUPS.keys()),
        selection_mode="multi",
        default=list(PILL_GROUPS.keys()),  # все 4 включены по умолчанию
        key="sa_activity_pills",
        format_func=_pill_group_label,
    )
    selected_pills = selected_pills or []

    # Дополнительные типы за период — отдельные pills, всегда видимы и все включены
    selected_extra: list[str] = []
    if extra_types:
        _extra_key = f"sa_extra_pills_{abs(hash(tuple(extra_types)))}"
        selected_extra = st.pills(
            "Доп. типы",
            extra_types,
            selection_mode="multi",
            default=extra_types,  # все включены по умолчанию
            key=_extra_key,
            label_visibility="collapsed",
            format_func=_activity_material_icon,
        )
        selected_extra = selected_extra or []

# Собираем итоговый набор Russian-имён для фильтра df
types_sel = []
for pill in selected_pills:
    for t in PILL_GROUPS[pill]:
        if t in types_all_list and t not in types_sel:
            types_sel.append(t)
for t in selected_extra:
    if t not in types_sel:
        types_sel.append(t)

# 2c. Группировка — segmented control с доступностью по периоду (ТЗ §4.1.5):
#   все 3 кнопки видны всегда; недоступные приглушаются через CSS
#   ≤30d → только Неделя; 31–179d → +Месяц; ≥180d → все три
GRP_ALL = ["Неделя", "Месяц", "Год"]
period_days_total = (end - start).days + 1
if period_days_total <= 30:
    grp_available = {"Неделя"}
    grp_disabled_idx = [2, 3]  # nth-child: Месяц, Год
    grp_hint = "Месяц от 31 дня · Год от 180 дней"
elif period_days_total < 180:
    grp_available = {"Неделя", "Месяц"}
    grp_disabled_idx = [3]
    grp_hint = "Год доступен от 180 дней"
else:
    grp_available = set(GRP_ALL)
    grp_disabled_idx = []
    grp_hint = ""

# CSS-инжекция: приглушаем недоступные кнопки сегментед-контрола в сайдбаре.
# В Streamlit 1.56 segmented_control рендерится как [data-testid="stButtonGroup"] с <button>'ами
# внутри. Ловим по индексу через nth-of-type внутри st-key-<key> wrapper'а.
if grp_disabled_idx:
    _disabled_selectors = ", ".join(
        f'[data-testid="stSidebar"] .st-key-sa_grouping button:nth-of-type({i})'
        for i in grp_disabled_idx
    )
    st.sidebar.markdown(
        f"<style>{_disabled_selectors} {{ opacity: 0.35 !important; pointer-events: none !important; cursor: not-allowed !important; }}</style>",
        unsafe_allow_html=True,
    )

prev_grp = st.session_state.get("_grp_choice", "Неделя")
default_grp = prev_grp if prev_grp in grp_available else "Неделя"

with st.sidebar.container(border=True, key="sa_grouping_tile"):
    agg_label = st.segmented_control(
        "Группировка",
        GRP_ALL,
        default=default_grp,
        selection_mode="single",
        key="sa_grouping",
        help=grp_hint or None,
    )
    agg_label = agg_label or default_grp
    # На случай если пользователь как-то прокликал недоступную — фолбэк
    if agg_label not in grp_available:
        agg_label = "Неделя"
    st.session_state["_grp_choice"] = agg_label
    if grp_hint:
        st.caption(f"⚠️ {grp_hint}")

AGG_COL = {"Неделя": "week", "Месяц": "month", "Год": "year"}[agg_label]
AGG_LOC = {"Неделя": "неделям", "Месяц": "месяцам", "Год": "годам"}[agg_label]
AGG_ACC = {"Неделя": "неделю",   "Месяц": "месяц",   "Год": "год"}[agg_label]
AGG_NOM = agg_label.lower()

st.sidebar.divider()

def _trigger_cloud_sync() -> tuple[bool, str]:
    """Дёргает GitHub Actions workflow_dispatch для cloud_sync.yml."""
    try:
        gh = st.secrets["github"]
        token = str(gh["token"])
        repo = str(gh.get("repo", "akhakhulin/sport_analytics"))
        workflow = str(gh.get("workflow", "cloud_sync.yml"))
        ref = str(gh.get("ref", "main"))
    except Exception:
        return False, "не настроен [github] token в Secrets"

    import urllib.request
    import urllib.error

    req = urllib.request.Request(
        f"https://api.github.com/repos/{repo}/actions/workflows/{workflow}/dispatches",
        method="POST",
        data=json.dumps({"ref": ref}).encode("utf-8"),
        headers={
            "Accept": "application/vnd.github+json",
            "Authorization": f"Bearer {token}",
            "Content-Type": "application/json",
            "X-GitHub-Api-Version": "2022-11-28",
        },
    )
    try:
        with urllib.request.urlopen(req, timeout=10) as resp:
            if resp.status == 204:
                return True, "cloud sync запущен"
            return False, f"HTTP {resp.status}"
    except urllib.error.HTTPError as e:
        body = e.read().decode("utf-8", errors="replace")[:120]
        return False, f"HTTP {e.code}: {body}"
    except Exception as exc:  # noqa: BLE001
        return False, f"ошибка: {exc}"


# 2d. SyncStatus pill (● Свежие / Устарело / Старые) + ⟳ refresh icon
def _sync_status() -> tuple[str, str]:
    """Возвращает (label, css_class) по свежести самой свежей активности."""
    last = df["day"].max() if not df.empty else None
    if last is None:
        return ("● Нет данных", "sa-status-old")
    age_h = (date.today() - last).days * 24
    if age_h < 24:
        return ("● Свежие", "sa-status-fresh")
    if age_h < 48:
        return ("● Устарело", "sa-status-stale")
    return ("● Старые", "sa-status-old")


_status_label, _status_class = _sync_status()
_status_col, _refresh_col = st.sidebar.columns([3, 1], gap="small")
with _status_col:
    st.markdown(
        f'<div class="sa-status {_status_class}">'
        f'<span class="dot"></span>{_status_label.lstrip("● ")}</div>',
        unsafe_allow_html=True,
    )
with _refresh_col:
    if st.button("⟳", key="sa_refresh", use_container_width=True):
        if IS_ADMIN:
            ok, msg = _trigger_cloud_sync()
            if ok:
                st.session_state["_refresh_msg"] = (
                    "success",
                    "☁️ Cloud sync запущен. Данные подтянутся через "
                    "30-60 сек — нажми ⟳ ещё раз через минуту.",
                )
            elif msg.startswith("не настроен"):
                # Github PAT не настроен — тихий fallback на сброс кэша
                st.session_state["_refresh_msg"] = (
                    "info", "Кэш сброшен. Свежие данные подтянутся "
                            "по расписанию (cron 02:00 UTC).",
                )
            else:
                # PAT есть, но запрос не прошёл — это уже стоит показать
                st.session_state["_refresh_msg"] = ("warning", f"⚠️ Cloud sync: {msg}")
        else:
            st.session_state["_refresh_msg"] = (
                "info", "Кэш сброшен. Свежие данные подтянутся сами "
                        "по расписанию (cron 02:00 UTC).",
            )
        st.cache_data.clear()
        st.rerun()

# Показываем результат последнего нажатия (не теряется при rerun)
_msg = st.session_state.pop("_refresh_msg", None)
if _msg:
    kind, text = _msg
    if kind == "success":
        st.sidebar.success(text, icon="✅")
    elif kind == "warning":
        st.sidebar.warning(text, icon="⚠️")
    else:
        st.sidebar.info(text, icon="ℹ️")

# endregion


# region Отфильтрованный срез

mask = (df["day"] >= start) & (df["day"] <= end) & (df["activity_type_ru"].isin(types_sel))
view = df[mask].copy()

# Реактивность: тост при смене фильтров + футер sidebar со статусом
filter_sig = (selected_athlete, start, end, agg_label, tuple(sorted(types_sel)))
prev_sig = st.session_state.get("_prev_filter_sig")
if prev_sig is not None and prev_sig != filter_sig:
    changed = []
    if prev_sig[0] != selected_athlete:
        changed.append(f"атлет → {selected_athlete}")
    if (prev_sig[1], prev_sig[2]) != (start, end):
        changed.append(f"период {start} → {end}")
    if prev_sig[3] != agg_label:
        changed.append(f"группировка → {agg_label}")
    if prev_sig[4] != tuple(sorted(types_sel)):
        changed.append("типы активностей")
    if changed:
        st.toast("Пересчитано: " + ", ".join(changed), icon="✅")
st.session_state["_prev_filter_sig"] = filter_sig

# 2e. Sidebar footer + модалка «О сессии»
days_in_range = (end - start).days + 1
last_in_db = df["day"].max() if not df.empty else None


@st.dialog("О сессии", width="small")
def _session_info_dialog():
    rendered = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    backend = "Turso (облако)" if dbm.is_turso() else "локально"
    st.markdown(f"**Атлет:** `{selected_athlete}`"
                + ("  (вы — администратор)" if IS_ADMIN else ""))
    st.markdown(f"**Активностей в выбранном срезе:** {len(view)}")
    st.markdown(f"**Дней в окне:** {days_in_range}")
    st.markdown(f"**Источник данных:** {backend}")
    st.markdown(f"**Последняя активность в БД:** `{last_in_db}`")
    st.markdown(f"**Дашборд отрисован:** `{rendered}`")
    diag = (
        f"athlete: {selected_athlete}\n"
        f"period: {start} → {end} ({days_in_range} d)\n"
        f"activities: {len(view)}\n"
        f"backend: {backend}\n"
        f"last_in_db: {last_in_db}\n"
        f"rendered: {rendered}\n"
    )
    st.code(diag, language=None)
    st.caption(
        "Скопируйте текст выше при репорте проблемы — пригодится для "
        "диагностики."
    )


st.sidebar.markdown(
    f'<div class="sa-foot">'
    f'📊 <b>{len(view)}</b> актив. · <b>{days_in_range}</b> дн.'
    f'</div>',
    unsafe_allow_html=True,
)
if st.sidebar.button("ⓘ О сессии", key="sa_session_info"):
    _session_info_dialog()
if st.sidebar.button("📄 PDF-экспорт", key="pdf_export", use_container_width=True):
    st.toast("PDF-экспорт ещё в разработке", icon="📄")

# endregion


# region Header + KPI

st.title(f"🏃 Аналитика Спортсмена · {selected_athlete}")
st.caption(
    f"👤 **{selected_athlete}**  ·  "
    f"📅 **{start}** → **{end}**  ·  📊 **{len(view)}** активностей  ·  "
    f"📐 группировка: **{AGG_NOM}**  ·  "
    f"🕐 {datetime.now().strftime('%H:%M:%S')}"
)


def _calc_age(birth_date: str | None) -> int | None:
    if not birth_date:
        return None
    try:
        bd = date.fromisoformat(birth_date)
    except Exception:
        return None
    today = date.today()
    return today.year - bd.year - ((today.month, today.day) < (bd.month, bd.day))


with st.expander("📋 Профиль и HR-зоны", expanded=False):
    profile = load_user_profile(selected_athlete)
    zones_df = load_hr_zones(selected_athlete)

    if profile is None and zones_df.empty:
        st.info(
            "Профиль ещё не синканы. После следующего синка (`sync.exe` "
            "локально или GitHub Actions для cloud-атлетов) данные появятся."
        )
    else:
        col_anthro, col_aerobic, col_zones = st.columns([1, 1, 1.4])

        with col_anthro:
            st.markdown("**Антропо**")
            if profile:
                age = _calc_age(profile.get("birth_date"))
                if age is not None:
                    st.write(f"🎂 **{age}** лет")
                if profile.get("height_cm"):
                    st.write(f"📏 **{int(profile['height_cm'])}** см")
                if profile.get("weight_kg"):
                    st.write(f"⚖️ **{profile['weight_kg']:.1f}** кг")
                if profile.get("gender"):
                    st.write(f"👤 {profile['gender']}")
            else:
                st.caption("—")

        with col_aerobic:
            st.markdown("**Аэробное**")
            if profile:
                vr = profile.get("vo2_max_running")
                vc = profile.get("vo2_max_cycling")
                if vr:
                    st.write(f"🏃 VO₂max бег: **{vr:.0f}**")
                if vc:
                    st.write(f"🚴 VO₂max вело: **{vc:.0f}**")
                if not vr and not vc:
                    st.caption("VO₂max не настроен")
                if profile.get("lactate_threshold_hr"):
                    st.write(f"🩸 LTHR: **{profile['lactate_threshold_hr']}** уд/мин")
            # Resting HR — берём из hr_zones (там точнее; в profile не приходит)
            if not zones_df.empty:
                rest = zones_df["resting_hr"].dropna()
                if len(rest):
                    st.write(f"🫀 Resting HR: **{int(rest.iloc[0])}** уд/мин")
                mx = zones_df["max_hr"].dropna()
                if len(mx):
                    st.write(f"❤️ Max HR: **{int(mx.iloc[0])}** уд/мин")

        with col_zones:
            if not zones_df.empty:
                sports = zones_df["sport"].tolist()
                # порядок: DEFAULT → RUNNING → CYCLING
                default_sport = (
                    "RUNNING" if "RUNNING" in sports else sports[0]
                )
                sport_label = {
                    "DEFAULT": "По умолчанию",
                    "RUNNING": "Бег",
                    "CYCLING": "Вело",
                }
                sport = st.radio(
                    "**Зоны для:**",
                    options=sports,
                    format_func=lambda s: sport_label.get(s, s),
                    index=sports.index(default_sport),
                    horizontal=True,
                    key="profile_hr_sport",
                )
                z = zones_df[zones_df["sport"] == sport].iloc[0]
                z_floors = [
                    int(z["zone1_floor"]), int(z["zone2_floor"]),
                    int(z["zone3_floor"]), int(z["zone4_floor"]),
                    int(z["zone5_floor"]),
                ]
                z_max = int(z["max_hr"]) if pd.notna(z["max_hr"]) else None
                rows = [
                    f"**Z1** ≤ {z_floors[1] - 1}",
                    f"**Z2** {z_floors[1]}–{z_floors[2] - 1}",
                    f"**Z3** {z_floors[2]}–{z_floors[3] - 1}",
                    f"**Z4** {z_floors[3]}–{z_floors[4] - 1}",
                    f"**Z5** ≥ {z_floors[4]}" + (f" (макс {z_max})" if z_max else ""),
                ]
                for r in rows:
                    st.write(r)
                if z["training_method"]:
                    st.caption(f"метод: {z['training_method']}")
            else:
                st.markdown("**Зоны**")
                st.caption("—")

# ----- KPI-блок -----
# Считаем previous-period для дельт
period_len = max(1, (end - start).days)
prev_end = start - timedelta(days=1)
prev_start = prev_end - timedelta(days=period_len)
prev_mask = (
    (df["day"] >= prev_start) & (df["day"] <= prev_end)
    & (df["activity_type_ru"].isin(types_sel))
)
view_prev = df[prev_mask]

kpi_w_now,  kpi_w_prev  = len(view), len(view_prev)
kpi_h_now,  kpi_h_prev  = view["duration_h"].sum(), (view_prev["duration_h"].sum() if len(view_prev) else 0.0)
kpi_km_now, kpi_km_prev = view["distance_km"].sum(), (view_prev["distance_km"].sum() if len(view_prev) else 0.0)
kpi_e_now,  kpi_e_prev  = (
    float(view["elevation_gain_m"].fillna(0).sum()),
    float(view_prev["elevation_gain_m"].fillna(0).sum()) if len(view_prev) else 0.0,
)
kpi_c_now,  kpi_c_prev  = view["calories"].sum(),    (view_prev["calories"].sum()    if len(view_prev) else 0.0)


def _avg_hr_weighted(_v: pd.DataFrame) -> float:
    """Средний пульс по периоду: avg_hr, взвешенный по длительности (только записи где HR писался)."""
    if _v is None or len(_v) == 0:
        return 0.0
    src = _v[(_v["avg_hr"].fillna(0) > 0) & (_v["duration_sec"].fillna(0) > 0)]
    if src.empty:
        return 0.0
    return float((src["avg_hr"] * src["duration_sec"]).sum() / src["duration_sec"].sum())


kpi_hr_now,  kpi_hr_prev  = _avg_hr_weighted(view), _avg_hr_weighted(view_prev)


def _delta_str(now: float, prev: float, mode: str = "pct", suffix: str = "") -> str | None:
    """Streamlit-формат дельты: '+12' или '-3%' (стрелки и цвет — авто от знака)."""
    if prev <= 0 or (mode == "abs" and now == prev) or (mode == "pct" and abs(now - prev) < 1e-9):
        return None
    if mode == "abs":
        d = now - prev
        return f"{int(d):+d}{suffix} vs пред."
    d = (now - prev) / prev * 100
    return f"{d:+.0f}% vs пред."


# Состояние drilldown'а: None | "workouts" | "hours" | "km"
kpi_drilldown = st.session_state.get("_kpi_drilldown")

SPORT_COLORS = {"Бег": "#97C459", "Велосипед": "#378ADD", "Плавание": "#1D9E75"}

# Запасная палитра для типов вне трёх основных групп (лыжи, лыжероллеры, и т.п.)
_TYPE_FALLBACK_PALETTE = [
    "#5F4FB0",  # фиолетовый
    "#D85A30",  # оранжевый
    "#0F6E56",  # тёмно-зелёный
    "#854F0B",  # коричневый
    "#A32D2D",  # красный
    "#185FA5",  # тёмно-синий
    "#888780",  # серый
]

# SVG-иконки видов спорта (из docs/sport_icons_pack.html)
_SPORT_ICONS_SVG = {
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
_ACTIVITY_ICON_MAP = {
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


def _sport_icon_html(activity_type_ru: str, size: int = 18, color: str | None = None) -> str:
    """Inline SVG-иконка вида спорта. Цвет по умолчанию — _type_color()."""
    name = _ACTIVITY_ICON_MAP.get(activity_type_ru, "other")
    body = _SPORT_ICONS_SVG.get(name, _SPORT_ICONS_SVG["other"])
    c = color or _type_color(activity_type_ru)
    return (
        f'<svg width="{size}" height="{size}" viewBox="0 0 24 24" '
        f'style="color:{c}; flex-shrink:0; vertical-align:middle;">{body}</svg>'
    )


def _sport_group(t: str) -> str:
    if t in ("Бег", "Беговая дорожка", "Трейл", "Стадион", "Виртуальный бег"):
        return "Бег"
    if t in ("Велосипед", "Велотренажёр", "Шоссейный велосипед",
             "Маунтинбайк", "Гравел", "Виртуальная вело"):
        return "Велосипед"
    if t in ("Бассейн", "Открытая вода", "Плавание"):
        return "Плавание"
    return "Прочее"


def _type_color(t: str) -> str:
    """Цвет конкретной активности: явные цвета для частых типов,
    SPORT_COLORS для Бег/Велик/Плав, иначе стабильный из fallback-палитры по hash."""
    if isinstance(t, str):
        # Лыжи: конёк — тёмно-синий, классика — светло-синий (палитра sport_icons_pack)
        if "конёк" in t.lower() or "конек" in t.lower():
            if t.startswith("Лыжероллеры"):
                return "#5F4FB0"  # фиолетовый
            return "#4A6FA5"  # тёмно-синий — конёк
        if "классика" in t.lower():
            if t.startswith("Лыжероллеры"):
                return "#8B6FB5"  # светло-фиолетовый — лыжероллеры классика
            return "#6B8AB5"  # светло-синий — классика
        if t.startswith("Лыжи"):
            return "#4A6FA5"  # дефолт для лыж — тёмно-синий
        if t.startswith("Лыжероллеры"):
            return "#5F4FB0"  # дефолт для лыжероллеров — фиолетовый
    grp = _sport_group(t)
    if grp in SPORT_COLORS:
        return SPORT_COLORS[grp]
    return _TYPE_FALLBACK_PALETTE[abs(hash(t)) % len(_TYPE_FALLBACK_PALETTE)]


def _render_activities_table(_view: pd.DataFrame) -> None:
    """Таблица активностей — для drilldown «Тренировок»."""
    show = _view[
        ["start_time_local", "activity_type_ru", "activity_name", "distance_km",
         "duration_h", "avg_hr", "max_hr", "training_effect_aer",
         "training_effect_ana", "calories"]
    ].copy()
    show["duration_h"] = show["duration_h"].round(2)
    show["distance_km"] = show["distance_km"].round(2)
    show = show.sort_values("start_time_local", ascending=False)
    show = show.rename(columns={
        "start_time_local": "Старт", "activity_type_ru": "Тип",
        "activity_name": "Название", "distance_km": "км", "duration_h": "ч",
        "avg_hr": "ср.HR", "max_hr": "макс.HR",
        "training_effect_aer": "TE аэр.", "training_effect_ana": "TE анаэр.",
        "calories": "кал",
    })
    st.dataframe(show, use_container_width=True, height=400)


def _render_hours_drilldown(_view: pd.DataFrame) -> None:
    """Drilldown «Часов» — разбивка по конкретным типам активности
    (по аналогии с Расстоянием: каждый тип отдельной строкой со своим цветом)."""
    if len(_view) == 0:
        st.info("Нет данных для выбранного периода.")
        return

    agg = (
        _view.groupby("activity_type_ru")["duration_h"].sum()
        .reset_index()
        .sort_values("duration_h", ascending=False)
    )
    total_h = float(agg["duration_h"].sum())
    if total_h <= 0:
        st.info("Нет часов для выбранного среза.")
        return

    st.markdown(
        f'<div style="font-size:13px; margin-bottom:10px;">'
        f'  Всего <b>{total_h:.1f} ч</b> по видам активности:'
        f'</div>',
        unsafe_allow_html=True,
    )

    for _, r in agg.iterrows():
        t = r["activity_type_ru"]
        pct = r["duration_h"] / total_h * 100 if total_h > 0 else 0
        color = _type_color(t)
        icon = _sport_icon_html(t, size=18)
        st.markdown(
            f'<div style="display:flex; align-items:center; gap:10px; padding:5px 0; font-size:13px;">'
            f'  <span style="min-width:170px; display:flex; align-items:center; gap:8px;">'
            f'    {icon}<span>{t}</span>'
            f'  </span>'
            f'  <span style="flex:1; height:8px; background:#F1EFE8; border-radius:4px; overflow:hidden;">'
            f'    <span style="display:block; height:100%; width:{pct:.1f}%; background:{color}; border-radius:4px;"></span>'
            f'  </span>'
            f'  <b style="min-width:75px; text-align:right;">{r["duration_h"]:.1f} ч</b>'
            f'  <span style="min-width:45px; color:#5F5E5A; text-align:right;">{pct:.1f}%</span>'
            f'</div>',
            unsafe_allow_html=True,
        )


def _render_km_drilldown(_view: pd.DataFrame) -> None:
    """Drilldown «Расстояние» — разбивка по конкретным типам активности
    (без бакета «Прочее»; каждый тип отдельной строкой со своим цветом)."""
    df_km = _view[_view["distance_km"] > 0].copy()
    if df_km.empty:
        st.info("Нет активностей с измеренным расстоянием в выбранном срезе.")
        return

    agg = (
        df_km.groupby("activity_type_ru")["distance_km"].sum()
        .reset_index()
        .sort_values("distance_km", ascending=False)
    )
    total_km = float(agg["distance_km"].sum())

    st.markdown(
        f'<div style="font-size:13px; margin-bottom:10px;">'
        f'  Всего <b>{total_km:.1f} км</b> по видам активности:'
        f'</div>',
        unsafe_allow_html=True,
    )

    for _, r in agg.iterrows():
        t = r["activity_type_ru"]
        pct = r["distance_km"] / total_km * 100 if total_km > 0 else 0
        color = _type_color(t)
        icon = _sport_icon_html(t, size=18)
        st.markdown(
            f'<div style="display:flex; align-items:center; gap:10px; padding:5px 0; font-size:13px;">'
            f'  <span style="min-width:170px; display:flex; align-items:center; gap:8px;">'
            f'    {icon}<span>{t}</span>'
            f'  </span>'
            f'  <span style="flex:1; height:8px; background:#F1EFE8; border-radius:4px; overflow:hidden;">'
            f'    <span style="display:block; height:100%; width:{pct:.1f}%; background:{color}; border-radius:4px;"></span>'
            f'  </span>'
            f'  <b style="min-width:75px; text-align:right;">{r["distance_km"]:.1f} км</b>'
            f'  <span style="min-width:45px; color:#5F5E5A; text-align:right;">{pct:.1f}%</span>'
            f'</div>',
            unsafe_allow_html=True,
        )


def _kpi_toggle(key: str) -> None:
    cur = st.session_state.get("_kpi_drilldown")
    st.session_state["_kpi_drilldown"] = None if cur == key else key


# Инжектим CSS активной карточки (синяя рамка + треугольник вниз)
if kpi_drilldown:
    st.markdown(
        f"""
<style>
[data-testid="stMain"] .st-key-kpi_card_{kpi_drilldown} {{
  position: relative !important;
}}
[data-testid="stMain"] .st-key-kpi_card_{kpi_drilldown} [data-testid="stMetric"] {{
  border: 2px solid var(--color-info) !important;
  border-radius: var(--r-lg) !important;
  background: #F7FAFD !important;
}}
[data-testid="stMain"] .st-key-kpi_card_{kpi_drilldown}::after {{
  content: '';
  position: absolute;
  bottom: -14px;
  left: 50%;
  transform: translateX(-50%);
  width: 0; height: 0;
  border-left: 12px solid transparent;
  border-right: 12px solid transparent;
  border-top: 14px solid var(--color-info);
  z-index: 11;
}}
[data-testid="stMain"] .st-key-kpi_card_{kpi_drilldown}::before {{
  content: '';
  position: absolute;
  bottom: -10px;
  left: 50%;
  transform: translateX(-50%);
  width: 0; height: 0;
  border-left: 9px solid transparent;
  border-right: 9px solid transparent;
  border-top: 11px solid var(--color-bg-block);
  z-index: 12;
}}
</style>
""",
        unsafe_allow_html=True,
    )

# Оборачиваем 6 KPI в expander «Всего»
with st.expander("Всего", expanded=True):
    cols = st.columns(6)

    # 1. Тренировок — overlay-button делает всю карточку кликабельной
    with cols[0]:
        with st.container(key="kpi_card_workouts"):
            st.metric("Тренировок", f"{kpi_w_now}", _delta_str(kpi_w_now, kpi_w_prev, "abs"))
            if st.button(" ", key="kpi_workouts_btn", use_container_width=True):
                _kpi_toggle("workouts")
                st.rerun()

    # 2. Время (формат «N ч NN мин»)
    with cols[1]:
        with st.container(key="kpi_card_hours"):
            st.metric("Время", fmt_hm(kpi_h_now), _delta_str(kpi_h_now, kpi_h_prev, "pct"))
            if st.button(" ", key="kpi_hours_btn", use_container_width=True):
                _kpi_toggle("hours")
                st.rerun()

    # 3. Средний пульс (взвешенный по duration) — без drilldown
    with cols[2]:
        with st.container(key="kpi_card_avghr"):
            _hr_value = f"{int(round(kpi_hr_now))} уд/мин" if kpi_hr_now > 0 else "—"
            st.metric(
                "Средний пульс",
                _hr_value,
                _delta_str(kpi_hr_now, kpi_hr_prev, "abs", suffix=" уд"),
            )

    # 4. Расстояние
    with cols[3]:
        with st.container(key="kpi_card_km"):
            st.metric("Расстояние", f"{kpi_km_now:.1f} км", _delta_str(kpi_km_now, kpi_km_prev, "pct"))
            if st.button(" ", key="kpi_km_btn", use_container_width=True):
                _kpi_toggle("km")
                st.rerun()

    # 5. Набор (elevation_gain) — без drilldown
    with cols[4]:
        with st.container(key="kpi_card_elevation"):
            st.metric(
                "Набор",
                f"{int(round(kpi_e_now)):,} м".replace(",", " "),
                _delta_str(kpi_e_now, kpi_e_prev, "pct"),
            )

    # 6. Калорий — без drilldown
    with cols[5]:
        with st.container(key="kpi_card_calories"):
            st.metric(
                "Калорий",
                f"{int(kpi_c_now):,} ккал".replace(",", " "),
                _delta_str(kpi_c_now, kpi_c_prev, "pct"),
            )

    # === Drilldown panel — внутри expander «Всего», на всю ширину ===
    if kpi_drilldown:
        _DD_TITLES = {
            "workouts": "Тренировок",
            "hours": "Часов",
            "km": "Расстояние",
        }
        with st.container(key="kpi_dd_panel"):
            st.markdown(
                f'<div class="kpi-dd-badge">★ детализация · {_DD_TITLES[kpi_drilldown]}</div>',
                unsafe_allow_html=True,
            )
            if kpi_drilldown == "workouts":
                _render_activities_table(view)
            elif kpi_drilldown == "hours":
                _render_hours_drilldown(view)
            elif kpi_drilldown == "km":
                _render_km_drilldown(view)

# endregion


# region HR зоны

with st.expander("⏱ Пульс: время в зонах", expanded=True):
    zone_total = pd.DataFrame(
        {
            "zone": [f"Z{i}" for i in range(1, 6)],
            "hours": [view[f"z{i}_sec"].sum() / 3600 for i in range(1, 6)],
        }
    )
    zone_total["zone_label"] = zone_total["zone"].map(ZONE_NAMES)
    zone_total["color"] = zone_total["zone"].map(ZONE_COLORS)

    _total_hours = zone_total["hours"].sum()

    if _total_hours <= 0:
        st.info("Нет данных по HR-зонам в выбранном срезе.")
    else:
        zone_total["pct"] = zone_total["hours"] / _total_hours * 100

        # Поляризация (Seiler 3-zone): L=Z1+Z2, M=Z3, H=Z4+Z5 — по часам, не по округлённым процентам
        _h = zone_total["hours"].tolist()
        _low_pct = (_h[0] + _h[1]) / _total_hours * 100
        _mid_pct = _h[2] / _total_hours * 100
        _high_pct = (_h[3] + _h[4]) / _total_hours * 100
        _poly_str = f"{round(_low_pct)}/{round(_mid_pct)}/{round(_high_pct)}"

        with st.container(border=True):
                # Donut с центральным текстом (общее время в зонах) — слева
                # Таблица Z5→Z1: имя · время · % — справа
                def _fmt_hm(h: float) -> str:
                    if h is None or h <= 0:
                        return "0"
                    total_min = int(round(h * 60))
                    if total_min < 60:
                        return f"{total_min} мин"
                    hh = total_min // 60
                    mm = total_min % 60
                    return f"{hh} ч {mm:02d} мин" if mm else f"{hh} ч"

                _total_label = _fmt_hm(_total_hours)
                pie_left, table_right = st.columns([1, 1.1])

                with pie_left:
                    fig = go.Figure(
                        go.Pie(
                            labels=zone_total["zone_label"],
                            values=zone_total["hours"],
                            marker=dict(colors=[ZONE_COLORS[z] for z in zone_total["zone"]]),
                            hole=0.65,
                            sort=False,
                            textinfo="none",
                            customdata=[[_fmt_hm(h)] for h in zone_total["hours"]],
                            hovertemplate="%{label}<br>%{customdata[0]}<extra></extra>",
                        )
                    )
                    fig.update_layout(
                        height=220,
                        showlegend=False,
                        margin=dict(t=10, b=10, l=10, r=10),
                        paper_bgcolor="rgba(0,0,0,0)",
                        plot_bgcolor="rgba(0,0,0,0)",
                        annotations=[
                            dict(
                                text=(
                                    f"<b style='font-size:18px;color:#2C2C2A;'>{_total_label}</b>"
                                    f"<br>"
                                    f"<span style='font-size:11px;color:#5F5E5A;'>Общее время</span>"
                                ),
                                x=0.5, y=0.5,
                                showarrow=False,
                                xanchor="center", yanchor="middle",
                            )
                        ],
                    )
                    st.plotly_chart(fig, use_container_width=True, config=PLOTLY_CONFIG)
                    st.markdown(
                        f'<div style="margin-top:6px; text-align:center;">'
                        f'  <span class="hrz-poly">✓ Поляризация {_poly_str}</span>'
                        f'  <span class="hrz-poly-hint">≈ Seiler 80/20</span>'
                        f'</div>',
                        unsafe_allow_html=True,
                    )

                with table_right:
                    rows_html = ""
                    # Z5 → Z1 (как в скриншоте-эталоне)
                    for _, _r in zone_total[::-1].iterrows():
                        _z = _r["zone"]
                        _color = _r["color"]
                        rows_html += (
                            f'<div style="display:flex; align-items:center; gap:10px; '
                            f'padding:5px 0; font-size:13px; border-bottom:0.5px solid rgba(0,0,0,0.08);">'
                            f'<span style="display:inline-flex; align-items:center; gap:6px; min-width:80px;">'
                            f'<span style="width:9px; height:9px; border-radius:2px; background:{_color};"></span>'
                            f'<b>{_z}</b><span style="color:#5F5E5A;">·</span>'
                            f'<span>{ZONE_NAMES[_z].split("·",1)[1].strip() if "·" in ZONE_NAMES[_z] else ZONE_NAMES[_z]}</span>'
                            f'</span>'
                            f'<span style="flex:1; text-align:right; color:#2C2C2A;">{_fmt_hm(_r["hours"])}</span>'
                            f'<span style="min-width:50px; text-align:right; color:#5F5E5A;">{_r["pct"]:.1f}%</span>'
                            f'</div>'
                        )
                    st.markdown(
                        f'<div style="padding:6px 4px;">{rows_html}</div>',
                        unsafe_allow_html=True,
                    )

        # Стили для пилюль Поляризации (используются внутри тайла под donut)
        st.markdown(
            '<style>'
            '.hrz-poly { display:inline-flex; align-items:center; gap:5px; '
            'background:#EAF3DE; color:#3B6D11; font-size:12px; padding:3px 10px; '
            'border-radius:5px; font-weight:500; }'
            '.hrz-poly-hint { font-size:11px; color:#5F5E5A; margin-left:10px; }'
            '</style>',
            unsafe_allow_html=True,
        )

    # Подробнее по периодам — вместо вложенного expander (Streamlit nested expanders не поддерживает)
    show_periods = st.toggle(
        "📊 Подробнее по периодам", value=False, key="hr_zones_show_periods"
    )
    if show_periods:
        # Динамика по периодам — без фильтра по активности и без переключения часы/проценты:
        # на bar показываем сразу часы (ось Y) и % сверху над столбиком.
        period = view.groupby(AGG_COL)[[f"z{i}_sec" for i in range(1, 6)]].sum() / 3600
        if not period.empty and period.values.sum() > 0:
            zone_cols = [f"z{i}_sec" for i in range(1, 6)]
            zone_names = [f"Z{i}" for i in range(1, 6)]

            period_nonzero = period[period.sum(axis=1) > 0].sort_index()
            n = len(period_nonzero)
            if n > 0:
                hdr_l, hdr_r = st.columns([3, 2])
                with hdr_l:
                    st.markdown(f"**HR-зоны по {AGG_LOC} (часы и %)**")
                with hdr_r:
                    size_label = st.radio(
                        "Размер графиков",
                        ["Мелкие", "Средние", "Крупные"],
                        index=1,
                        horizontal=True,
                        key="donut_size",
                        label_visibility="collapsed",
                    )
                size_map = {"Мелкие": 5, "Средние": 4, "Крупные": 3}
                cell_height_map = {"Мелкие": 260, "Средние": 360, "Крупные": 480}
                cols_per_row = size_map[size_label]
                cell_height = cell_height_map[size_label]

                periods_list = list(period_nonzero.iterrows())

                def _week_range(d):
                    end = d + pd.Timedelta(days=6)
                    if d.year != end.year:
                        return f"{d.strftime('%d %b %Y')} – {end.strftime('%d %b %Y')}"
                    if d.month != end.month:
                        return f"{d.strftime('%d %b')} – {end.strftime('%d %b %Y')}"
                    return f"{d.day}–{end.day} {d.strftime('%b %Y')}"

                def _title_for(label):
                    if AGG_COL == "year":
                        return label.strftime("%Y")
                    if AGG_COL == "month":
                        return label.strftime("%b %Y")
                    if AGG_COL == "week":
                        return _week_range(label)
                    return label.strftime("%d %b")

                for start_idx in range(0, n, cols_per_row):
                    chunk = periods_list[start_idx : start_idx + cols_per_row]
                    cols = st.columns(cols_per_row)
                    for i, (label, row) in enumerate(chunk):
                        vals = [row[col] for col in zone_cols]
                        tot = sum(vals) or 1
                        pcts = [v / tot * 100 for v in vals]
                        title_str = _title_for(label)

                        dur_text = [fmt_dur(v) for v in vals]
                        # На bar выводим оба значения: % сверху, время снизу (две строки через <br>)
                        text = [
                            (f"{p:.0f}%<br>{d}" if v > 0 else "")
                            for p, d, v in zip(pcts, dur_text, vals)
                        ]
                        bar = go.Figure(
                            go.Bar(
                                x=zone_names,
                                y=vals,  # Y-ось = часы
                                marker=dict(color=[ZONE_COLORS[z] for z in zone_names]),
                                text=text,
                                textposition="outside",
                                cliponaxis=False,
                                customdata=[[d, p] for d, p in zip(dur_text, pcts)],
                                hovertemplate="%{x}: %{customdata[0]} · %{customdata[1]:.1f}%<extra></extra>",
                            )
                        )
                        bar.update_layout(
                            height=cell_height,
                            title=dict(text=title_str, x=0.5, xanchor="center",
                                       font=dict(size=14)),
                            showlegend=False,
                            margin=dict(t=40, b=30, l=10, r=10),
                            xaxis=dict(title="", fixedrange=True),
                            yaxis=dict(title="", fixedrange=True,
                                       rangemode="tozero"),
                            uniformtext_minsize=8,
                            uniformtext_mode="hide",
                        )
                        with cols[i]:
                            st.plotly_chart(bar, use_container_width=True,
                                            config=PLOTLY_CONFIG)
                    # Пустые колонки в последнем ряду — без контента, сохраняют ширину
                    for j in range(len(chunk), cols_per_row):
                        with cols[j]:
                            st.empty()

# endregion


# region Детализация · Время / Расстояние (Вариант A — Сумма)
# Прототип: docs/drilldown_time_variant_a.html

def _render_detalization(_view: pd.DataFrame, agg_col: str, metric: str) -> None:
    """Стэк-bar по периодам + таблица сумм по типам + футер min/avg/max.

    metric ∈ {"time", "distance"} управляет источником данных и форматом.
    """
    if metric == "time":
        col_value = "duration_h"
        unit_short = "ч"
        col_table_h = "Часов"
        fmt_total = lambda v: fmt_hm(v)            # «N ч NN мин»
        fmt_cell = lambda v: f"{v:.1f}"            # часы с десятой
        fmt_avg = lambda v: f"{v:.1f}"
        fmt_minmax = lambda v: f"{v:.1f} ч"
        view_eff = _view
    else:  # distance
        col_value = "distance_km"
        unit_short = "км"
        col_table_h = "км"
        fmt_total = lambda v: f"{v:.1f} км"
        fmt_cell = lambda v: f"{v:.1f}"
        fmt_avg = lambda v: f"{v:.1f}"
        fmt_minmax = lambda v: f"{v:.1f} км"
        view_eff = _view[_view["distance_km"].fillna(0) > 0]

    if len(view_eff) == 0 or view_eff[col_value].sum() <= 0:
        st.info("Нет данных для выбранного периода.")
        return

    _total = float(view_eff[col_value].sum())
    _per = view_eff.groupby(agg_col)[col_value].sum().sort_index()
    _per_nonzero = _per[_per > 0]
    _n_periods = max(1, len(_per_nonzero))
    _avg_per = _total / _n_periods

    if len(_per_nonzero) > 1 and _per_nonzero.mean() > 0:
        _cv = float(_per_nonzero.std() / _per_nonzero.mean() * 100)
    else:
        _cv = 0.0

    if _cv < 15:
        _cv_label = "стабильно"
    elif _cv < 30:
        _cv_label = "нормально"
    elif _cv < 50:
        _cv_label = "хаотично"
    else:
        _cv_label = "нерегулярно"

    _per_unit = {"week": "нед", "month": "мес", "year": "год"}.get(agg_col, "период")

    # Top row: Stat row слева + Размер графика справа
    top_l, top_r = st.columns([3, 2])
    with top_l:
        st.markdown(
            f'<div style="display:flex; align-items:baseline; gap:12px; flex-wrap:wrap;'
            f' padding-bottom:12px; margin-bottom:14px; border-bottom:0.5px solid rgba(0,0,0,0.1);">'
            f'<span style="font-size:24px; font-weight:500; line-height:1;">{fmt_total(_total)}</span>'
            f'<span style="font-size:11px; color:#5F5E5A;">'
            f'{fmt_avg(_avg_per)} {unit_short}/{_per_unit} · CV {_cv:.0f}% · {_cv_label}'
            f'</span></div>',
            unsafe_allow_html=True,
        )
    with top_r:
        size_label = st.radio(
            "Размер графика",
            ["Мелкие", "Средние", "Крупные"],
            index=1,
            horizontal=True,
            key=f"detal_{metric}_size",
            label_visibility="collapsed",
        )
    _chart_h = {"Мелкие": 240, "Средние": 320, "Крупные": 440}[size_label]

    chart_col, table_col = st.columns([1, 0.45])

    with chart_col:
        _grp = view_eff.groupby([agg_col, "activity_type_ru"])[col_value].sum().reset_index()
        _grp = _grp[_grp[col_value] > 0]
        if not _grp.empty:
            _unique_types = list(_grp["activity_type_ru"].unique())
            _color_map = {t: _type_color(t) for t in _unique_types}
            _tot_per = _grp.groupby(agg_col)[col_value].sum().reset_index()

            fig_dd = go.Figure()
            for _t in _unique_types:
                _sub = _grp[_grp["activity_type_ru"] == _t]
                fig_dd.add_trace(
                    go.Bar(
                        x=_sub[agg_col], y=_sub[col_value],
                        name=_t,
                        marker_color=_color_map[_t],
                        hovertemplate=f"<b>{_t}</b>: %{{y:.1f}} {unit_short}<extra></extra>",
                    )
                )
            fig_dd.add_trace(
                go.Scatter(
                    x=_tot_per[agg_col], y=_tot_per[col_value],
                    text=[f"{v:.1f}" for v in _tot_per[col_value]],
                    mode="text", textposition="top center",
                    textfont=dict(size=10, color="#2C2C2A"),
                    showlegend=False, hoverinfo="skip",
                )
            )
            fig_dd.update_layout(
                barmode="stack",
                height=_chart_h,
                margin=dict(t=20, b=10, l=10, r=10),
                paper_bgcolor="rgba(0,0,0,0)",
                plot_bgcolor="rgba(0,0,0,0)",
                xaxis=dict(title="", showgrid=False, fixedrange=True),
                yaxis=dict(title=unit_short, showgrid=True,
                           gridcolor="rgba(0,0,0,0.05)",
                           fixedrange=True, rangemode="tozero"),
                showlegend=False,  # своя HTML-легенда ниже с SVG-иконками
                hovermode="x unified",
            )
            st.plotly_chart(fig_dd, use_container_width=True, config=PLOTLY_CONFIG)

            # Кастомная HTML-легенда: SVG-иконка + название по типу активности
            _legend_parts = []
            for _t in _unique_types:
                _ico = _sport_icon_html(_t, size=14)
                _legend_parts.append(
                    f'<span style="display:inline-flex; align-items:center; gap:5px;">'
                    f'{_ico}<span>{_t}</span></span>'
                )
            st.markdown(
                f'<div style="display:flex; flex-wrap:wrap; gap:14px; '
                f'justify-content:center; padding:4px 8px 0; font-size:11px; color:#2C2C2A;">'
                f'{"".join(_legend_parts)}'
                f'</div>',
                unsafe_allow_html=True,
            )

    with table_col:
        _sum_by_type = view_eff.groupby("activity_type_ru")[col_value].sum().sort_values(ascending=False)
        _sum_by_type = _sum_by_type[_sum_by_type > 0]

        _rows = (
            '<div style="font-size:10px; font-weight:500; margin-bottom:8px;'
            ' color:#5F5E5A; text-transform:uppercase; letter-spacing:0.5px;">'
            'Сумма за период</div>'
            '<div style="font-size:11px;">'
            '<div style="display:grid; grid-template-columns:1fr 90px; padding:4px 6px;'
            ' border-bottom:0.5px solid rgba(0,0,0,0.15); font-weight:500;'
            ' color:#5F5E5A; font-size:9px; text-transform:uppercase;'
            ' letter-spacing:0.4px;"><span>Тип</span>'
            f'<span style="text-align:right;">{col_table_h}</span></div>'
        )
        for _t, _h in _sum_by_type.items():
            _pct = _h / _total * 100 if _total > 0 else 0
            _ico = _sport_icon_html(_t, size=16)
            _rows += (
                f'<div style="display:grid; grid-template-columns:1fr 90px; padding:6px 6px;'
                f' border-bottom:0.5px solid rgba(0,0,0,0.08); align-items:center;">'
                f'<span style="display:flex; align-items:center; gap:7px;">'
                f'{_ico}'
                f'<span style="overflow:hidden; text-overflow:ellipsis; white-space:nowrap;">{_t}</span>'
                f'</span>'
                f'<span style="text-align:right; font-variant-numeric:tabular-nums;">'
                f'{fmt_cell(_h)} · {_pct:.0f}%</span>'
                f'</div>'
            )
        _rows += (
            f'<div style="display:grid; grid-template-columns:1fr 90px; padding:7px 6px;'
            f' background:#F5F4EF; border-radius:4px; margin-top:4px; font-weight:500;'
            f' align-items:center;">'
            f'<span>Итого</span>'
            f'<span style="text-align:right; font-variant-numeric:tabular-nums;">{fmt_total(_total)}</span>'
            f'</div></div>'
        )
        st.markdown(_rows, unsafe_allow_html=True)

    if len(_per_nonzero) > 0:
        st.markdown(
            f'<div style="display:flex; gap:14px; font-size:10px; color:#5F5E5A;'
            f' margin-top:10px; padding-top:10px; border-top:0.5px solid rgba(0,0,0,0.1);'
            f' flex-wrap:wrap; align-items:center;">'
            f'<span style="margin-left:auto;">'
            f'min <b style="color:#2C2C2A;">{fmt_minmax(_per_nonzero.min())}</b> · '
            f'avg <b style="color:#2C2C2A;">{fmt_minmax(_per_nonzero.mean())}</b> · '
            f'max <b style="color:#2C2C2A;">{fmt_minmax(_per_nonzero.max())}</b>'
            f'</span></div>',
            unsafe_allow_html=True,
        )

    # ===== Подробнее по периодам — сетка bar-чартов: один период = один чарт,
    # на оси X активности из sidebar pills, на Y — часы (только для metric="time")
    if metric == "time":
        st.markdown(
            '<div style="margin-top:14px;"></div>',
            unsafe_allow_html=True,
        )
        show_periods_dd = st.toggle(
            "📊 Подробнее по периодам",
            value=False,
            key=f"detal_{metric}_periods_show",
        )
        if show_periods_dd:
            _hdr_l, _hdr_r = st.columns([3, 2])
            with _hdr_l:
                st.markdown(
                    f'<div style="font-size:13px; font-weight:500; padding-top:6px;">'
                    f'**Часы по {_per_unit}, разбивка по активностям**'
                    f'</div>'.replace("**", ""),
                    unsafe_allow_html=True,
                )
            with _hdr_r:
                _size_p = st.radio(
                    "Размер",
                    ["Мелкие", "Средние", "Крупные"],
                    index=1,
                    horizontal=True,
                    key=f"detal_{metric}_periods_size",
                    label_visibility="collapsed",
                )
            _size_map = {"Мелкие": 5, "Средние": 4, "Крупные": 3}
            _cell_h_map = {"Мелкие": 220, "Средние": 280, "Крупные": 360}
            _cols_per_row = _size_map[_size_p]
            _cell_h = _cell_h_map[_size_p]

            # Группируем мелкие типы в супер-группы (PILL_GROUPS),
            # чтобы ось X не превращалась в простыню из 10+ столбиков.
            # Лыжи · конёк/классика и Лыжероллеры остаются индивидуально —
            # их различать важно для тренировочного контекста.
            def _super_group(t: str) -> str:
                for pill, sub in PILL_GROUPS.items():
                    if t in sub:
                        return pill  # «🏃 Бег», «🚴 Велик», «🏊 Плав.», «💪 Сила»
                return t  # Лыжи · конёк / Лыжи · классика / Лыжероллеры · ... — раздельно

            # Активные супер-группы из sidebar pills + extra
            _active_groups: list[str] = []
            for _pill in (selected_pills or []):
                if _pill not in _active_groups:
                    _active_groups.append(_pill)
            for _t in (selected_extra or []):
                _g = _super_group(_t)
                if _g not in _active_groups:
                    _active_groups.append(_g)

            # Только группы что реально присутствуют в view_eff
            _groups_in_view = set(view_eff["activity_type_ru"].apply(_super_group).unique())
            _active_groups = [g for g in _active_groups if g in _groups_in_view]

            if not _active_groups:
                st.info("Нет активностей за выбранный период.")
            else:
                # Заранее агрегируем часы по периоду × супер-группе и фильтруем
                # периоды с нулевой суммой
                _view_g = view_eff.copy()
                _view_g["_super"] = _view_g["activity_type_ru"].apply(_super_group)
                _agg_p = (_view_g.groupby([agg_col, "_super"])[col_value].sum()
                                  .reset_index())
                _agg_p = _agg_p[_agg_p[col_value] > 0]
                _periods_with_data = sorted(_agg_p[agg_col].unique())
                _n = len(_periods_with_data)

                def _period_title(p):
                    if agg_col == "year":
                        return p.strftime("%Y")
                    if agg_col == "month":
                        return p.strftime("%b %Y")
                    end_p = p + pd.Timedelta(days=6)
                    if p.month != end_p.month:
                        return f"{p.strftime('%d %b')} – {end_p.strftime('%d %b')}"
                    return f"{p.day}–{end_p.day} {p.strftime('%b')}"

                if _n == 0:
                    st.info("Нет периодов с данными.")
                else:
                    for _start in range(0, _n, _cols_per_row):
                        _chunk = _periods_with_data[_start:_start + _cols_per_row]
                        _cols = st.columns(_cols_per_row)
                        for _i, _p in enumerate(_chunk):
                            _p_data = _agg_p[_agg_p[agg_col] == _p].set_index("_super")[col_value]
                            _hours = [float(_p_data.get(g, 0.0)) for g in _active_groups]
                            _total_p = sum(_hours) or 1
                            _pcts = [v / _total_p * 100 for v in _hours]
                            _texts = [
                                f"{p:.0f}%<br>{v:.1f} ч" if v > 0 else ""
                                for p, v in zip(_pcts, _hours)
                            ]
                            _colors = [_type_color(g) for g in _active_groups]

                            _bar = go.Figure(go.Bar(
                                x=_active_groups,
                                y=_hours,
                                marker=dict(color=_colors),
                                text=_texts,
                                textposition="outside",
                                cliponaxis=False,
                            ))
                            _bar.update_layout(
                                height=_cell_h,
                                title=dict(text=_period_title(_p), x=0.5, xanchor="center",
                                           font=dict(size=13)),
                                showlegend=False,
                                margin=dict(t=40, b=40, l=10, r=10),
                                xaxis=dict(title="", fixedrange=True, tickangle=-25),
                                yaxis=dict(title="ч", fixedrange=True, rangemode="tozero",
                                           gridcolor="rgba(0,0,0,0.05)"),
                                paper_bgcolor="rgba(0,0,0,0)",
                                plot_bgcolor="rgba(0,0,0,0)",
                                uniformtext_minsize=8,
                                uniformtext_mode="hide",
                            )
                            with _cols[_i]:
                                st.plotly_chart(_bar, use_container_width=True, config=PLOTLY_CONFIG)
                        for _j in range(len(_chunk), _cols_per_row):
                            with _cols[_j]:
                                st.empty()


with st.expander("📊 Детализация · Время", expanded=True):
    _render_detalization(view, AGG_COL, metric="time")

with st.expander("📊 Детализация · Расстояние", expanded=True):
    _render_detalization(view, AGG_COL, metric="distance")

# endregion


# region Объём — заменён блоками «📊 Детализация · Время / Расстояние»
# endregion


# region Recovery

def _sparkline_line_svg(values: list[float], color: str, fill_color: str | None = None,
                        norm_band: tuple[float, float] | None = None,
                        width: int = 220, height: int = 44) -> str:
    """Тонкая sparkline (polyline) с опциональной полосой «нормы» сзади."""
    vals = [v for v in values if v is not None and not pd.isna(v)]
    if len(vals) < 2:
        return f'<svg width="100%" height="{height}" viewBox="0 0 {width} {height}"></svg>'
    vmin, vmax = min(vals), max(vals)
    if vmax - vmin < 1e-9:
        vmax = vmin + 1
    pad = 4
    inner_h = height - pad * 2
    pts = []
    for i, v in enumerate(vals):
        x = (i / (len(vals) - 1)) * width
        y = pad + (1 - (v - vmin) / (vmax - vmin)) * inner_h
        pts.append(f"{x:.1f},{y:.1f}")
    band = ""
    if norm_band:
        lo, hi = norm_band
        if vmax > lo and vmin < hi:
            yhi = pad + (1 - (min(hi, vmax) - vmin) / (vmax - vmin)) * inner_h
            ylo = pad + (1 - (max(lo, vmin) - vmin) / (vmax - vmin)) * inner_h
            band = (f'<rect x="0" y="{yhi:.1f}" width="{width}" '
                    f'height="{(ylo - yhi):.1f}" fill="{fill_color or color}" opacity="0.10"/>')
    return (
        f'<svg width="100%" height="{height}" viewBox="0 0 {width} {height}" '
        f'preserveAspectRatio="none" style="display:block;">'
        f'{band}'
        f'<polyline points="{" ".join(pts)}" fill="none" '
        f'stroke="{color}" stroke-width="1.4" stroke-linejoin="round"/>'
        f'</svg>'
    )


def _sparkline_bars_svg(values: list[float], target: float | None = None,
                        color: str = "#185FA5", width: int = 220, height: int = 44) -> str:
    """Sparkline-bar для сна: столбики + опциональная пунктирная линия цели."""
    vals = [v if (v is not None and not pd.isna(v)) else 0 for v in values]
    if not vals:
        return f'<svg width="100%" height="{height}"></svg>'
    vmax = max([*vals, target or 0])
    if vmax <= 0:
        vmax = 1
    n = len(vals)
    bw = max(2, (width - (n - 1) * 1) / max(n, 1))
    rects = []
    for i, v in enumerate(vals):
        bh = (v / vmax) * (height - 4)
        x = i * (bw + 1)
        y = (height - 2) - bh
        rects.append(f'<rect x="{x:.1f}" y="{y:.1f}" width="{bw:.1f}" '
                     f'height="{bh:.1f}" fill="{color}" rx="0.5"/>')
    target_line = ""
    if target and target > 0:
        ty = (height - 2) - (target / vmax) * (height - 4)
        target_line = (f'<line x1="0" y1="{ty:.1f}" x2="{width}" y2="{ty:.1f}" '
                       f'stroke="#1D9E75" stroke-width="0.8" stroke-dasharray="3,2"/>')
    return (
        f'<svg width="100%" height="{height}" viewBox="0 0 {width} {height}" '
        f'preserveAspectRatio="none" style="display:block;">'
        f'{target_line}{"".join(rects)}'
        f'</svg>'
    )


def _delta_arrow_str(d: float, kind: str) -> tuple[str, str]:
    """Возвращает (текст, цвет) для дельты. kind = 'rhr' (↓ хорошо) | 'hrv' (↑ хорошо)."""
    if d == 0 or pd.isna(d):
        return ("", "#5F5E5A")
    if kind == "rhr":
        good = d < 0
    else:  # hrv
        good = d > 0
    arrow = "↓" if d < 0 else "↑"
    color = "#3B6D11" if good else "#A32D2D"
    return (f"{arrow} {int(round(d)):+d}", color)


if not daily.empty:
    recovery = daily[(daily["day"] >= start) & (daily["day"] <= end)].copy().sort_values("day")
    if not recovery.empty:
        with st.expander("💤 Recovery-метрики · RHR · HRV · сон", expanded=False):
            # Предыдущий период — для дельт
            _prev_len = max(1, (end - start).days)
            _prev_end = start - timedelta(days=1)
            _prev_start = _prev_end - timedelta(days=_prev_len)
            recovery_prev = daily[(daily["day"] >= _prev_start) & (daily["day"] <= _prev_end)].copy()

            cols = st.columns(3)

            # ===== 1. Пульс покоя (RHR) =====
            with cols[0]:
                with st.container(border=True):
                    if "resting_hr" in recovery and recovery["resting_hr"].notna().any():
                        rhr = recovery["resting_hr"].dropna()
                        rhr_now = float(rhr.iloc[-1])
                        rhr_avg = float(rhr.mean())
                        rhr_prev_avg = (
                            float(recovery_prev["resting_hr"].dropna().mean())
                            if "resting_hr" in recovery_prev and recovery_prev["resting_hr"].notna().any()
                            else 0.0
                        )
                        d = rhr_now - rhr_prev_avg if rhr_prev_avg else 0
                        d_text, d_color = _delta_arrow_str(d, "rhr")
                        norm_ref = 50
                        if rhr_avg < norm_ref:
                            foot_color, foot_text = "#3B6D11", f"лучше нормы ({norm_ref} ср.)"
                        elif rhr_avg < norm_ref + 10:
                            foot_color, foot_text = "#5F5E5A", f"в норме (~{norm_ref})"
                        else:
                            foot_color, foot_text = "#854F0B", f"выше нормы ({norm_ref})"
                        spark = _sparkline_line_svg(
                            rhr.tolist(), color="#185FA5",
                            fill_color="#378ADD",
                            norm_band=(40, 60),
                        )
                        st.markdown(
                            f'<div style="display:flex; justify-content:space-between; '
                            f'align-items:center; font-size:12px; font-weight:500;">'
                            f'<span>💗 Пульс покоя</span>'
                            f'<span style="color:{d_color}; font-size:11px;">{d_text}</span>'
                            f'</div>'
                            f'<div style="display:flex; align-items:baseline; gap:5px; margin-top:4px;">'
                            f'<span style="font-size:24px; font-weight:500; line-height:1;">{rhr_now:.0f}</span>'
                            f'<span style="font-size:11px; color:#5F5E5A;">уд/мин</span>'
                            f'</div>'
                            f'{spark}'
                            f'<div style="font-size:10px; color:{foot_color}; margin-top:4px;">{foot_text}</div>',
                            unsafe_allow_html=True,
                        )
                    else:
                        st.markdown('<div style="font-size:12px; color:#5F5E5A;">💗 Пульс покоя — нет данных</div>',
                                    unsafe_allow_html=True)

            # ===== 2. HRV за ночь =====
            with cols[1]:
                with st.container(border=True):
                    if "hrv_night" in recovery and recovery["hrv_night"].notna().any():
                        hrv = recovery["hrv_night"].dropna()
                        hrv_now = float(hrv.iloc[-1])
                        hrv_avg = float(hrv.mean())
                        hrv_prev_avg = (
                            float(recovery_prev["hrv_night"].dropna().mean())
                            if "hrv_night" in recovery_prev and recovery_prev["hrv_night"].notna().any()
                            else 0.0
                        )
                        d = hrv_now - hrv_prev_avg if hrv_prev_avg else 0
                        d_text, d_color = _delta_arrow_str(d, "hrv")
                        if 60 <= hrv_avg <= 80:
                            foot_color, foot_text = "#3B6D11", "в полосе нормы (60–80)"
                        elif hrv_avg < 60:
                            foot_color, foot_text = "#854F0B", "ниже нормы (60–80)"
                        else:
                            foot_color, foot_text = "#3B6D11", "выше нормы (60–80)"
                        spark = _sparkline_line_svg(
                            hrv.tolist(), color="#0F6E56",
                            fill_color="#1D9E75",
                            norm_band=(60, 80),
                        )
                        st.markdown(
                            f'<div style="display:flex; justify-content:space-between; '
                            f'align-items:center; font-size:12px; font-weight:500;">'
                            f'<span>📊 HRV за ночь</span>'
                            f'<span style="color:{d_color}; font-size:11px;">{d_text}</span>'
                            f'</div>'
                            f'<div style="display:flex; align-items:baseline; gap:5px; margin-top:4px;">'
                            f'<span style="font-size:24px; font-weight:500; line-height:1;">{hrv_now:.0f}</span>'
                            f'<span style="font-size:11px; color:#5F5E5A;">мс</span>'
                            f'</div>'
                            f'{spark}'
                            f'<div style="font-size:10px; color:{foot_color}; margin-top:4px;">{foot_text}</div>',
                            unsafe_allow_html=True,
                        )
                    else:
                        st.markdown('<div style="font-size:12px; color:#5F5E5A;">📊 HRV за ночь — нет данных</div>',
                                    unsafe_allow_html=True)

            # ===== 3. Сон =====
            with cols[2]:
                with st.container(border=True):
                    if "sleep_h" in recovery and recovery["sleep_h"].notna().any():
                        sleep = recovery["sleep_h"].dropna()
                        sleep_now = float(sleep.iloc[-1])
                        sleep_avg = float(sleep.mean())
                        target_h = 8.0
                        if sleep_avg >= target_h:
                            head_color, head_text = "#3B6D11", f"✓ {sleep_avg:.1f}ч ср."
                            foot_color = "#3B6D11"
                            foot_text = f"среднее за период {sleep_avg:.1f} ч"
                        else:
                            head_color = "#854F0B"
                            head_text = f"⚠ {sleep_avg:.1f}ч ср."
                            deficit = target_h - sleep_avg
                            foot_color, foot_text = "#854F0B", f"дефицит {deficit:.1f}ч от цели {target_h:.0f}ч"
                        bars = _sparkline_bars_svg(
                            sleep.tolist(), target=target_h, color="#185FA5",
                        )
                        st.markdown(
                            f'<div style="display:flex; justify-content:space-between; '
                            f'align-items:center; font-size:12px; font-weight:500;">'
                            f'<span>🌙 Сон</span>'
                            f'<span style="color:{head_color}; font-size:11px;">{head_text}</span>'
                            f'</div>'
                            f'<div style="display:flex; align-items:baseline; gap:5px; margin-top:4px;">'
                            f'<span style="font-size:24px; font-weight:500; line-height:1;">{sleep_now:.1f}</span>'
                            f'<span style="font-size:11px; color:#5F5E5A;">часов вчера</span>'
                            f'</div>'
                            f'{bars}'
                            f'<div style="font-size:10px; color:{foot_color}; margin-top:4px;">{foot_text}</div>',
                            unsafe_allow_html=True,
                        )
                    else:
                        st.markdown('<div style="font-size:12px; color:#5F5E5A;">🌙 Сон — нет данных</div>',
                                    unsafe_allow_html=True)

# endregion


# region Training Load (PMC)

with st.expander("🏋️ Training load · CTL/ATL/TSB", expanded=False):
    # LTHR по умолчанию: 91% от 95-перцентиля max HR — близко к реальному порогу
    if not df["max_hr"].dropna().empty:
        default_lthr = int(df["max_hr"].dropna().quantile(0.95) * 0.91)
    else:
        default_lthr = 165

    cfg_col, _ = st.columns([1, 3])
    with cfg_col:
        lthr = st.number_input(
            "LTHR (порог анаэр., уд/мин)",
            min_value=120,
            max_value=210,
            value=default_lthr,
            step=1,
            help="Lactate Threshold HR. По умолчанию ≈ 91% от 95-перцентиля макс. пульса в данных. "
                 "Точнее всего — взять из теста или из настроек зон в Garmin Connect.",
            key="lthr_value",
        )

    pmc = compute_pmc(df, lthr)
    if pmc.empty:
        st.info("Нет данных для расчёта PMC — нужны активности с avg_hr и duration.")
    else:
        last = pmc.iloc[-1]
        c1, c2, c3, c4 = st.columns(4)
        c1.metric("CTL · фитнес", f"{last['CTL']:.1f}")
        c2.metric("ATL · усталость", f"{last['ATL']:.1f}")
        c3.metric("TSB · форма", f"{last['TSB']:+.1f}")
        c4.metric("TSS вчера", f"{pmc['tss'].iloc[-2] if len(pmc) > 1 else 0:.0f}")

        pmc_view = pmc[(pmc["day"] >= start) & (pmc["day"] <= end)]

        fig = go.Figure()
        # TSS — серые столбики на фоне
        fig.add_trace(go.Bar(
            x=pmc_view["day"], y=pmc_view["tss"],
            name="TSS дня", marker_color="#D0CEC8", opacity=0.6,
            hovertemplate="%{x}<br>TSS: %{y:.0f}<extra></extra>",
        ))
        # CTL · фитнес — синий (TrainingPeaks стандарт)
        fig.add_trace(go.Scatter(
            x=pmc_view["day"], y=pmc_view["CTL"],
            name="CTL · фитнес", mode="lines",
            line=dict(color="#185FA5", width=2.5),
            hovertemplate="%{x}<br>CTL: %{y:.1f}<extra></extra>",
        ))
        # ATL · усталость — коралловый
        fig.add_trace(go.Scatter(
            x=pmc_view["day"], y=pmc_view["ATL"],
            name="ATL · усталость", mode="lines",
            line=dict(color="#D85A30", width=2),
            hovertemplate="%{x}<br>ATL: %{y:.1f}<extra></extra>",
        ))
        # TSB · форма — амбер пунктирный
        fig.add_trace(go.Scatter(
            x=pmc_view["day"], y=pmc_view["TSB"],
            name="TSB · форма", mode="lines",
            line=dict(color="#BA7517", width=2, dash="dash"),
            yaxis="y2",
            hovertemplate="%{x}<br>TSB: %{y:+.1f}<extra></extra>",
        ))

        # Зоны TSB справа цветными полосами
        fig.add_hrect(y0=25, y1=100, line_width=0, fillcolor="#3498db",
                      opacity=0.06, layer="below", yref="y2")
        fig.add_hrect(y0=5, y1=25, line_width=0, fillcolor="#2ecc71",
                      opacity=0.06, layer="below", yref="y2")
        fig.add_hrect(y0=-10, y1=5, line_width=0, fillcolor="#f39c12",
                      opacity=0.06, layer="below", yref="y2")
        fig.add_hrect(y0=-30, y1=-10, line_width=0, fillcolor="#e67e22",
                      opacity=0.08, layer="below", yref="y2")
        fig.add_hrect(y0=-100, y1=-30, line_width=0, fillcolor="#e74c3c",
                      opacity=0.10, layer="below", yref="y2")

        fig.update_layout(
            height=480,
            title="Performance Management Chart",
            yaxis=dict(title="CTL / ATL / TSS", rangemode="tozero"),
            yaxis2=dict(title="TSB", overlaying="y", side="right",
                        showgrid=False, zeroline=True, zerolinecolor="#7f8c8d"),
            legend=dict(orientation="h", y=-0.15),
            hovermode="x unified",
            margin=dict(t=50, b=20),
        )
        show_chart(fig, "pmc")

        st.caption(
            "**TSB · форма**: > +25 — недотренированность · "
            "+5..+25 — пик/перед стартом · "
            "−10..+5 — оптимум для развития · "
            "−30..−10 — высокая нагрузка (норма во время блока) · "
            "< −30 — переутомление, пора снижать."
        )

# endregion


# region Таблица активностей — переехала в drilldown «Тренировок» в KPI-блоке «Всего»
# endregion


