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


@st.dialog(" ", width="large")
def _zoom_dialog(fig_dict: dict, title: str = "") -> None:
    """Открывает график в большом модальном окне (~80% экрана)."""
    fig = go.Figure(fig_dict)
    fig.update_layout(height=720, title=title or fig.layout.title.text or "")
    st.plotly_chart(fig, use_container_width=True)


def show_chart(fig, key: str, height: int | None = None, expandable: bool = True) -> None:
    """Рендер графика + кнопка «🔍 Развернуть» под ним (открывает модалку)."""
    if height is not None:
        fig.update_layout(height=height)
    st.plotly_chart(fig, use_container_width=True, key=f"chart_{key}")
    if expandable:
        if st.button("🔍 Развернуть", key=f"zoom_btn_{key}", help="Открыть на ~80% экрана"):
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
    page_title="Garmin Dashboard",
    layout="wide",
    page_icon="🏃",
    initial_sidebar_state="expanded",
)


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
    df = _read_sql("SELECT DISTINCT athlete_id FROM activities ORDER BY athlete_id")
    return df["athlete_id"].tolist() if not df.empty else []


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

# Селектор атлета: тренер видит всех, обычный — только себя
all_athletes = list_athletes()
if IS_ADMIN and all_athletes:
    default_idx = all_athletes.index(MY_ATHLETE) if MY_ATHLETE in all_athletes else 0
    selected_athlete = st.sidebar.selectbox(
        "👤 Атлет",
        all_athletes,
        index=default_idx,
        help="Тренер видит всех атлетов в общей БД.",
    )
else:
    selected_athlete = MY_ATHLETE

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

preset = st.sidebar.radio(
    "Период",
    ["7 дней", "30 дней", "90 дней", "365 дней", "Всё", "Свой диапазон"],
    index=2,
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
    days_map = {"7 дней": 7, "30 дней": 30, "90 дней": 90, "365 дней": 365}
    end = max_day
    start = min_day if preset == "Всё" else end - timedelta(days=days_map[preset])

types_all = sorted(df["activity_type_ru"].dropna().unique())
types_sel = st.sidebar.multiselect(
    "Типы активности",
    types_all,
    default=types_all,
)

agg_label = st.sidebar.radio(
    "Группировка", ["Неделя", "Месяц", "Год"], index=0, horizontal=True
)
AGG_COL = {"Неделя": "week", "Месяц": "month", "Год": "year"}[agg_label]
AGG_LOC = {"Неделя": "неделям", "Месяц": "месяцам", "Год": "годам"}[agg_label]
AGG_ACC = {"Неделя": "неделю",   "Месяц": "месяц",   "Год": "год"}[agg_label]
AGG_NOM = agg_label.lower()

st.sidebar.divider()

if st.sidebar.button("🔄 Обновить из БД", use_container_width=True,
                     help="Сбросить кэш и перечитать данные (если только что прошёл sync)"):
    st.cache_data.clear()
    st.toast("Кэш очищен, читаю свежие данные...", icon="🔄")
    st.rerun()

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

# Sidebar footer
days_in_range = (end - start).days + 1
last_in_db = df["day"].max() if not df.empty else None
st.sidebar.caption(
    f"👤 **{selected_athlete}**" + (" (админ)" if IS_ADMIN else "") + "\n\n"
    f"📊 **{len(view)}** активностей · **{days_in_range}** дн.\n\n"
    f"📦 {'Turso (облако)' if dbm.is_turso() else 'локально'}\n\n"
    f"📅 Последняя в БД: **{last_in_db}**\n\n"
    f"🕐 Отрисовано: {datetime.now().strftime('%H:%M:%S')}"
)

# endregion


# region Header + KPI

st.title("🏃 Garmin Dashboard")
st.caption(
    f"👤 **{selected_athlete}**  ·  "
    f"📅 **{start}** → **{end}**  ·  📊 **{len(view)}** активностей  ·  "
    f"📐 группировка: **{AGG_NOM}**  ·  "
    f"🕐 {datetime.now().strftime('%H:%M:%S')}"
)

c1, c2, c3, c4, c5 = st.columns(5)
c1.metric("Тренировок", f"{len(view)}")
c2.metric("Часов", f"{view['duration_h'].sum():.1f}")
c3.metric("Километров", f"{view['distance_km'].sum():.1f}")
c4.metric("TE (аэр. ср.)", f"{view['training_effect_aer'].mean():.2f}" if len(view) else "—")
c5.metric("Калорий", f"{view['calories'].sum():.0f}")

st.divider()

# endregion


# region HR зоны

with st.expander("⏱ Время в HR-зонах", expanded=True):
    zone_total = pd.DataFrame(
        {
            "zone": [f"Z{i}" for i in range(1, 6)],
            "hours": [view[f"z{i}_sec"].sum() / 3600 for i in range(1, 6)],
        }
    )
    zone_total["zone_label"] = zone_total["zone"].map(ZONE_NAMES)
    zone_total["color"] = zone_total["zone"].map(ZONE_COLORS)

    left, right = st.columns([1, 1])

    with left:
        if zone_total["hours"].sum() > 0:
            fig = px.bar(
                zone_total,
                x="zone_label",
                y="hours",
                color="zone",
                color_discrete_map=ZONE_COLORS,
                text=zone_total["hours"].apply(fmt_dur),
                custom_data=["hours"],
            )
            fig.update_traces(
                textposition="outside",
                hovertemplate="%{x}: %{text}<extra></extra>",
            )
            fig.update_layout(
                showlegend=False,
                xaxis_title="",
                yaxis_title="часов",
                height=360,
                title="Время в HR-зонах",
            )
            show_chart(fig, "hr_zones_bar")
        else:
            st.info("Нет данных по HR-зонам в выбранном срезе.")

    with right:
        total = zone_total["hours"].sum()
        if total > 0:
            zone_total["pct"] = zone_total["hours"] / total * 100
            legend_labels = [
                f"{name} — {pct:.1f}%"
                for name, pct in zip(zone_total["zone_label"], zone_total["pct"])
            ]
            fig = go.Figure(
                go.Pie(
                    labels=legend_labels,
                    values=zone_total["hours"],
                    marker=dict(colors=[ZONE_COLORS[z] for z in zone_total["zone"]]),
                    hole=0.45,
                    sort=False,
                    textinfo="none",
                    customdata=[[fmt_dur(h)] for h in zone_total["hours"]],
                    hovertemplate="%{label}<br>%{customdata[0]}<extra></extra>",
                )
            )
            fig.update_layout(
                height=360,
                title="Распределение HR-зон",
                showlegend=True,
                legend=dict(
                    orientation="v",
                    yanchor="middle", y=0.5,
                    xanchor="left", x=1.02,
                    font=dict(size=13),
                    itemclick=False, itemdoubleclick=False,
                ),
                margin=dict(t=50, b=20, l=10, r=10),
            )
            show_chart(fig, "hr_zones_pie")

    # Динамика по периодам (неделя/месяц)
    view_mode = st.radio(
        "Вид",
        ["Часы", "Проценты"],
        index=1 if AGG_COL == "month" else 0,
        horizontal=True,
        key="hr_zones_view_mode",
    )

    period = view.groupby(AGG_COL)[[f"z{i}_sec" for i in range(1, 6)]].sum() / 3600
    if not period.empty and period.values.sum() > 0:
        zone_cols = [f"z{i}_sec" for i in range(1, 6)]
        zone_names = [f"Z{i}" for i in range(1, 6)]

        period_nonzero = period[period.sum(axis=1) > 0].sort_index()
        n = len(period_nonzero)
        if n > 0:
            size_label = st.radio(
                "Размер графиков",
                ["Мелкие", "Средние", "Крупные", "Огромные"],
                index=1,
                horizontal=True,
                key="donut_size",
            )
            size_map = {"Мелкие": 5, "Средние": 4, "Крупные": 3, "Огромные": 2}
            cell_height_map = {"Мелкие": 260, "Средние": 360, "Крупные": 480, "Огромные": 640}
            cols_per_row = size_map[size_label]
            cell_height = cell_height_map[size_label]

            units_label = "%" if view_mode == "Проценты" else "часы"
            st.markdown(f"**HR-зоны по {AGG_LOC} ({units_label})**")

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
                    if view_mode == "Проценты":
                        y_vals = pcts
                        text = [f"{p:.0f}%" if p > 0 else "" for p in pcts]
                        hover = "%{x}: %{y:.0f}%<br>%{customdata}<extra></extra>"
                    else:
                        y_vals = vals
                        text = dur_text
                        hover = "%{x}: %{customdata}<extra></extra>"
                    bar = go.Figure(
                        go.Bar(
                            x=zone_names,
                            y=y_vals,
                            marker=dict(color=[ZONE_COLORS[z] for z in zone_names]),
                            text=text,
                            textposition="outside",
                            cliponaxis=False,
                            customdata=dur_text,
                            hovertemplate=hover,
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
                        st.plotly_chart(bar, use_container_width=True)
                # Пустые колонки в последнем ряду — без контента, сохраняют ширину
                for j in range(len(chunk), cols_per_row):
                    with cols[j]:
                        st.empty()

            # Лупа: увеличенный donut выбранного периода
            def _period_label(d):
                if AGG_COL == "year":
                    return d.strftime("%Y")
                if AGG_COL == "month":
                    return d.strftime("%B %Y")
                return f"Неделя {_week_range(d)}"

            period_labels = {d: _period_label(d) for d in period_nonzero.index}
            zoom_key = st.selectbox(
                "🔍 Приблизить",
                options=list(period_labels.keys()),
                format_func=lambda d: period_labels[d],
                index=len(period_labels) - 1,
                key="hr_zoom_period",
            )
            if zoom_key is not None:
                zrow = period_nonzero.loc[zoom_key]
                zvals = [zrow[col] for col in zone_cols]
                ztotal = sum(zvals)
                zfig = go.Figure(
                    go.Pie(
                        labels=[ZONE_NAMES[z] for z in zone_names],
                        values=zvals,
                        marker=dict(colors=[ZONE_COLORS[z] for z in zone_names]),
                        hole=0.55,
                        textinfo="label+percent",
                        textposition="outside",
                        sort=False,
                        customdata=[[fmt_dur(v)] for v in zvals],
                        hovertemplate=(
                            "%{label}<br>"
                            "%{customdata[0]} (%{percent})<extra></extra>"
                        ),
                    )
                )
                zfig.update_layout(
                    height=520,
                    title=(
                        f"{period_labels[zoom_key]} — всего "
                        f"{fmt_dur(ztotal)}"
                    ),
                    showlegend=False,
                    margin=dict(t=60, b=20, l=20, r=20),
                )
                show_chart(zfig, "hr_zones_zoom")

# endregion


# region Объём

with st.expander(f"📅 Объём по {AGG_LOC}", expanded=True):
    agg = view.groupby(AGG_COL).agg(
        activities=("activity_id", "count"),
        km=("distance_km", "sum"),
        hours=("duration_h", "sum"),
        te_aer=("training_effect_aer", "mean"),
    ).reset_index()

    col1, col2 = st.columns(2)
    with col1:
        fig = px.bar(agg, x=AGG_COL, y="hours",
                     labels={AGG_COL: agg_label, "hours": "Часов"})
        fig.update_layout(height=320, title=f"Часы за {AGG_ACC}")
        show_chart(fig, "vol_hours")
    with col2:
        fig = px.bar(agg, x=AGG_COL, y="km",
                     labels={AGG_COL: agg_label, "km": "км"})
        fig.update_layout(height=320, title=f"Километры за {AGG_ACC}")
        show_chart(fig, "vol_km")

    # Разбивка по типам активности
    by_type = view.groupby([AGG_COL, "activity_type_ru"]).agg(
        hours=("duration_h", "sum"),
        count=("activity_id", "count"),
    ).reset_index()
    if not by_type.empty:
        fig = px.bar(
            by_type, x=AGG_COL, y="hours", color="activity_type_ru",
            labels={AGG_COL: agg_label, "hours": "Часов", "activity_type_ru": "Тип"},
        )
        fig.update_layout(height=350, barmode="stack",
                          title=f"Часы по типам активности ({AGG_NOM})")
        show_chart(fig, "vol_by_type")

# endregion


# region Recovery

if not daily.empty:
    recovery = daily[(daily["day"] >= start) & (daily["day"] <= end)].copy()
    if not recovery.empty:
        with st.expander("💤 Восстановление", expanded=False):
            cols = st.columns(3)
            if "resting_hr" in recovery:
                with cols[0]:
                    fig = px.line(recovery.sort_values("day"), x="day", y="resting_hr",
                                  labels={"day": "", "resting_hr": "RHR"})
                    fig.update_layout(height=280, title="Пульс покоя")
                    show_chart(fig, "rec_rhr")
            if "hrv_night" in recovery:
                with cols[1]:
                    fig = px.line(recovery.sort_values("day"), x="day", y="hrv_night",
                                  labels={"day": "", "hrv_night": "HRV, мс"})
                    fig.update_layout(height=280, title="HRV за ночь")
                    show_chart(fig, "rec_hrv")
            if "sleep_h" in recovery:
                with cols[2]:
                    fig = px.bar(recovery.sort_values("day"), x="day", y="sleep_h",
                                 labels={"day": "", "sleep_h": "часов"})
                    fig.update_layout(height=280, title="Сон")
                    show_chart(fig, "rec_sleep")

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
            name="TSS дня", marker_color="#bdc3c7", opacity=0.5,
            hovertemplate="%{x}<br>TSS: %{y:.0f}<extra></extra>",
        ))
        fig.add_trace(go.Scatter(
            x=pmc_view["day"], y=pmc_view["CTL"],
            name="CTL · фитнес", mode="lines",
            line=dict(color="#27ae60", width=2.5),
            hovertemplate="%{x}<br>CTL: %{y:.1f}<extra></extra>",
        ))
        fig.add_trace(go.Scatter(
            x=pmc_view["day"], y=pmc_view["ATL"],
            name="ATL · усталость", mode="lines",
            line=dict(color="#e67e22", width=2),
            hovertemplate="%{x}<br>ATL: %{y:.1f}<extra></extra>",
        ))
        fig.add_trace(go.Scatter(
            x=pmc_view["day"], y=pmc_view["TSB"],
            name="TSB · форма", mode="lines",
            line=dict(color="#2980b9", width=2, dash="dash"),
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


# region Таблица активностей

with st.expander(f"📋 Активности ({len(view)})", expanded=False):
    show = view[
        [
            "start_time_local",
            "activity_type_ru",
            "activity_name",
            "distance_km",
            "duration_h",
            "avg_hr",
            "max_hr",
            "training_effect_aer",
            "training_effect_ana",
            "calories",
        ]
    ].copy()
    show["duration_h"] = show["duration_h"].round(2)
    show["distance_km"] = show["distance_km"].round(2)
    show = show.sort_values("start_time_local", ascending=False)
    show = show.rename(
        columns={
            "start_time_local": "Старт",
            "activity_type_ru": "Тип",
            "activity_name": "Название",
            "distance_km": "км",
            "duration_h": "ч",
            "avg_hr": "ср.HR",
            "max_hr": "макс.HR",
            "training_effect_aer": "TE аэр.",
            "training_effect_ana": "TE анаэр.",
            "calories": "кал",
        }
    )
    st.dataframe(show, use_container_width=True, height=400)

# endregion
