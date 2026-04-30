"""
Сравнение периодов — отдельная страница multipage app.
Спека: docs/Сравнение периодов/SPECIFICATION_period_comparison.md

Вся логика — в comparison_view.render(). Эта же функция используется
в tab2 главного дашборда.
"""

from __future__ import annotations

from pathlib import Path

import pandas as pd
import streamlit as st
from dotenv import load_dotenv

load_dotenv()

import auth  # noqa: E402
auth.apply_secrets_to_env()
import db as dbm  # noqa: E402
from comparison_view import render as render_comparison  # noqa: E402

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


# ===== Селектор атлета =====
all_athletes_df = _read_sql(
    "SELECT DISTINCT athlete_id FROM activities ORDER BY athlete_id"
)
all_athletes = (
    all_athletes_df["athlete_id"].tolist() if not all_athletes_df.empty else [MY_ATHLETE]
)

if IS_ADMIN and len(all_athletes) > 1:
    selected_athlete = st.sidebar.selectbox(
        "👤 Атлет",
        all_athletes,
        index=all_athletes.index(MY_ATHLETE) if MY_ATHLETE in all_athletes else 0,
        key="cmp_page_athlete_select",
    )
else:
    selected_athlete = MY_ATHLETE
    st.sidebar.markdown(
        f'<div style="font-size:11px; color:#5F5E5A; text-transform:uppercase; '
        f'letter-spacing:0.5px; font-weight:500; margin-bottom:4px;">👤 Атлет</div>'
        f'<div style="font-size:13px;">{selected_athlete}</div>',
        unsafe_allow_html=True,
    )

df = load_activities(selected_athlete)


# ===== Рендер общим модулем =====
render_comparison(df, key_prefix="cmp_page", show_title=True)
