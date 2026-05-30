"""Telegram-команды бота."""
from __future__ import annotations

import logging
from datetime import date, timedelta

from telegram import Update
from telegram.ext import ContextTypes

from . import activity_check, briefs, config, db, morning, plan_reader, weekly_digest
from . import jarvis_routing

# Lazy-import JarvisAgent — отсутствие anthropic API ключа не должно ломать
# импорт handlers (старые команды работают без него)
_jarvis_agent = None


def _get_jarvis():
    global _jarvis_agent
    if _jarvis_agent is None:
        from . import jarvis_agent as _ja
        _jarvis_agent = _ja.JarvisAgent()
    return _jarvis_agent


# Telegram limit per message — 4096; режем с запасом
_TG_CHUNK = 3800

log = logging.getLogger("bot.handlers")


_FEELING_LABEL = {"fire": "🔥 огонь", "normal": "👍 норм", "tired": "😴 тяжко"}


async def cmd_start(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """При /start запоминаем chat_id (если ещё не записан)."""
    chat_id = update.effective_chat.id
    user = update.effective_user
    saved = db.get_chat_id()
    if not saved:
        db.save_chat_id(chat_id)
        await update.message.reply_text(
            f"Привет, {user.first_name}! 👋\n\n"
            f"Твой chat_id ({chat_id}) сохранён. Я готов работать.\n\n"
            f"Команды:\n"
            f"/today — план + утренние данные\n"
            f"/last — последняя тренировка\n"
            f"/week — сводка недели\n"
            f"/check — принудительно проверить новые активности\n"
            f"/help — список команд"
        )
        log.info(f"Бот привязан к chat_id={chat_id} (user={user.username})")
    else:
        if str(chat_id) != str(saved):
            await update.message.reply_text(
                "⚠️ Этот бот уже привязан к другому пользователю. "
                "Если это ошибка — обратись к админу."
            )
            log.warning(f"Попытка /start от чужого chat_id={chat_id} (привязан к {saved})")
            return
        await update.message.reply_text("Я уже работаю с тобой ✅. /help — список команд.")


async def cmd_help(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    if not _is_authorized(update):
        return
    await update.message.reply_text(
        "📋 Команды:\n\n"
        "/today — план на сегодня + утренние данные + брифы\n"
        "/brief — отдельно брифы по силовой / кор / плиометрике на сегодня\n"
        "/last — последняя записанная тренировка + анализ\n"
        "/week — сводка плана текущей недели\n"
        "/vo2 — Garmin VO2max + trend + помесячный прогноз\n"
        "/supps (или /bads) — рекомендации БАДов на сегодня по типу тренировки\n"
        "/feel [огонь|норм|тяжко] [текст] — фидбек по последней тренировке\n"
        "/digest — недельный дайджест прямо сейчас (авто — вс 20:00)\n"
        "/check — принудительно дёрнуть Garmin sync и проверить новые активности\n"
        "/status — диагностика: жив ли бот, когда последний heartbeat\n"
        "/help — это сообщение\n\n"
        "Утренний отчёт приходит автоматически при включении ПК.\n"
        "Анализ тренировок — каждые 30 минут на новых активностях."
    )


async def cmd_status(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Диагностика: жив ли бот, состояние компонентов."""
    if not _is_authorized(update):
        return

    from datetime import datetime, timezone
    import os

    last_hb = db.get_last_heartbeat()
    if last_hb:
        try:
            hb_dt = datetime.fromisoformat(last_hb).replace(tzinfo=timezone.utc)
            now = datetime.now(timezone.utc)
            age_sec = (now - hb_dt).total_seconds()
            age_str = (
                f"{int(age_sec)}с назад"
                if age_sec < 60
                else f"{int(age_sec // 60)}м {int(age_sec % 60)}с назад"
            )
            hb_status = "✅" if age_sec < 120 else "⚠️"
        except Exception:
            age_str = last_hb
            hb_status = "ℹ️"
    else:
        age_str = "ещё не было"
        hb_status = "⚠️"

    garmin_client = context.application.bot_data.get("garmin_client")
    garmin_status = "✅ готов" if garmin_client else "❌ не инициализирован"

    pid = os.getpid()
    plan_path = config.PLAN_EXCEL
    plan_status = "✅ найден" if plan_path.exists() else "❌ НЕТ"

    text = (
        f"🤖 Статус бота\n\n"
        f"PID: {pid}\n"
        f"Heartbeat: {hb_status} {age_str}\n"
        f"Garmin: {garmin_status}\n"
        f"План: {plan_status} ({plan_path.name})\n"
        f"Polling: каждые {config.ACTIVITY_POLL_INTERVAL_MIN} мин\n"
        f"Утреннее окно: {config.MORNING_HOUR_RANGE[0]:02d}:00–{config.MORNING_HOUR_RANGE[1]:02d}:00"
    )
    await update.message.reply_text(text)


async def cmd_today(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    if not _is_authorized(update):
        return
    today = date.today()
    text = morning.compose_morning_message(today)
    await update.message.reply_text(text)
    # Брифы по силовой / кор / плиометрике если есть на сегодня
    sessions = plan_reader.for_date(today)
    for brief_text in briefs.for_today(sessions):
        await update.message.reply_text(brief_text)


def _detect_supplement_scenario(sessions: list) -> str:
    """Определить сценарий БАДов по сессиям дня.

    Возвращает: 'C' (скоростная) > 'B' (длительная) > 'A' (лёгкая) > 'rest'.
    """
    if not sessions:
        return "rest"
    # Только отдых
    if all((s.type or "").lower() == "отдых" for s in sessions):
        return "rest"
    # Скоростная работа (приоритет 1)
    speed_keywords = ("темп", "мпк", "ускорен", "интервал", "контр", "race", "5×1", "перегруз")
    speed_types = ("плиометрика", "контроль")
    for s in sessions:
        t = (s.type or "").lower()
        text = (s.text or "").lower()
        if t in speed_types:
            return "C"
        if any(kw in text for kw in speed_keywords):
            return "C"
    # Длительная (приоритет 2)
    long_types = ("вело-длит", "бег-длит")
    for s in sessions:
        t = (s.type or "").lower()
        if t in long_types:
            return "B"
        # >2 ч в утреннем слоте — длительная
        if s.part == "утро" and (s.hours or 0) >= 2.0:
            return "B"
    return "A"


def _format_supplements(scenario: str, sessions: list) -> str:
    """Сформировать текст рекомендаций БАДов на день."""
    from datetime import date as _date
    today = _date.today()
    weekday = ["Пн", "Вт", "Ср", "Чт", "Пт", "Сб", "Вс"][today.weekday()]
    date_str = f"{weekday} {today.strftime('%d.%m')}"

    lines = [f"💊 БАДы на сегодня ({date_str})"]
    lines.append("")

    # Plan summary
    if sessions:
        lines.append("📋 План:")
        for s in sessions:
            icon = "☀" if s.part == "утро" else "🌙"
            lines.append(f"  {icon} {s.text}")
        lines.append("")

    if scenario == "rest":
        lines.append("☀ Сценарий: ОТДЫХ — нет тренировки")
        lines.append("")
        lines.append("Только базовые витамины:")
        lines.append("  • Завтрак: Omega 3 1-3 капс + D3+K2 1/2 таб (с жирной едой)")
        lines.append("  • Обед −30 мин: Цитофлавин 2 таб")
        lines.append("  • Перед сном: Цинк 1 таб")
        lines.append("")
        lines.append("Pre-workout БАДы (Citrulline / Carnitine / Гипоксен) пропустить.")
        return "\n".join(lines)

    # Все сценарии — есть тренировка
    has_morning = any(s.part == "утро" and (s.type or "").lower() != "отдых" for s in sessions)
    has_evening = any(s.part == "вечер" for s in sessions)

    if scenario == "A":
        lines.append("☀ Сценарий A — ЛЁГКАЯ УТРЕННЯЯ натощак")
        lines.append("(восст бег / Z1 вело / лёгкая аэробная)")
    elif scenario == "B":
        lines.append("🏔 Сценарий B — ДЛИТЕЛЬНАЯ после завтрака")
        lines.append("(длит вело Сб 2:30-3:00 / длит бег Вс 2:00-2:30)")
    elif scenario == "C":
        lines.append("⚡ Сценарий C — СКОРОСТНАЯ работа")
        lines.append("(темп / МПК / интервалы / гонка / прыжковая)")
    lines.append("")

    if scenario == "A":
        lines.append("🌅 Утро:")
        lines.append("  7:00 подъём → вода 300 мл")
        lines.append("  7:15 (за 60') → L-Citrulline 6 г + Женьшень 2 таб")
        lines.append("  7:30 (за 45') → L-Carnitine 1-2 капс + 1 ч.л. мёда")
        lines.append("  ❌ Гипоксен — пропустить (легко)")
        lines.append("")
        lines.append("🏃 Тренировка → вода без еды")
        lines.append("")
        lines.append("🍳 После:")
        lines.append("  Сразу → L-Glutamine 5-10 г")
        lines.append("  За 30' до завтрака → Цитофлавин 2 таб (1-й)")
        lines.append("  Завтрак → Omega 3 + D3+K2")
    elif scenario == "B":
        lines.append("🌅 Утро:")
        lines.append("  7:30 завтрак: каша/яйца + Omega 3 + D3+K2")
        lines.append("  8:00 (за 60-90' до старта) → Цитофлавин 2 таб + L-Citrulline 6 г + Женьшень")
        lines.append("  9:00 (за 30-45') → ⭐ ГИПОКСЕН 500 мг ОБЯЗАТЕЛЬНО")
        lines.append("  9:00 (за 30') → L-Carnitine 1-2 капс (без мёда — пища дала инсулин)")
        lines.append("")
        lines.append("🏃 9:30-10:00 СТАРТ длительной")
        lines.append("  В пути: 600-800 мл воды/час (густая кровь!) + электролиты")
        lines.append("  Углеводы: 30-60 г/час (1 банан/гель каждые 30-45 мин)")
        lines.append("")
        lines.append("После:")
        lines.append("  L-Glutamine 5-10 г + углеводы 60 г в течение 30 мин")
        lines.append("  💧 СТИМОЛ 1 пакет (антиастеник, восстановление)")
    elif scenario == "C":
        lines.append("🌅 Утро:")
        lines.append("  За 90' до трен: лёгкий перекус (банан + хлеб + творог, ~250 ккал)")
        lines.append("  За 60' → Цитофлавин 2 таб + L-Citrulline 6 г + Женьшень")
        lines.append("  За 45' → ⭐⭐ ГИПОКСЕН 500 мг (на интервалах нужен больше всего)")
        lines.append("  За 30' → L-Carnitine 1-2 капс")
        lines.append("")
        lines.append("⚡ Тренировка → изотоник + 1 гель в середине если интенсив >40'")
        lines.append("")
        lines.append("После (recovery window 30 мин):")
        lines.append("  L-Glutamine 5-10 г + углеводы 60 г + белок 20 г")
        lines.append("  💧 СТИМОЛ 1 пакет (антиастеник, восстановление)")
        lines.append("  Опц.: ещё 1 пакет утром перед завтраком если усталость накоплена")

    lines.append("")
    if has_evening and scenario in ("A", "B", "C"):
        lines.append("🌙 Вечерняя тренировка (СТ ОМВ / лёгкая Z1):")
        lines.append("  17:30-18:00 (за 60-90') → лёгкий перекус (~200 ккал)")
        lines.append("  ⚠️ НЕ дублируем утренние Citrulline / Carnitine / Женьшень — 1 раз в день")
        # Determine if Гипоксен дробится
        if scenario == "A":
            lines.append("  За 30-45' до тяжёлой СТ ОМВ ПИК → Гипоксен 500 мг")
            lines.append("  (или 250 мг если утром уже принимал)")
        else:
            lines.append("  За 30' до СТ → Гипоксен 250 мг (если утром было 500, всего 750/день — потолок)")
        lines.append("  После: L-Glutamine 5 г + углеводы 30-40 г + белок 20 г")
    lines.append("")
    lines.append("Базовые на день:")
    lines.append("  Обед −30 мин → Цитофлавин 2 таб (2-й приём)")
    lines.append("  💊 После ужина (~20:00) → КардиоМагнил 75 мг (АСК+Mg, антиагрегант)")
    lines.append("  Перед сном → Цинк 1 таб")

    # Курсовой Стимол: проверяем особые периоды
    today_iso = today.isoformat()
    stimol_course = _check_stimol_course(today_iso, sessions)
    if stimol_course:
        lines.append("")
        lines.append("💧 СТИМОЛ КУРС (особый период):")
        lines.append(f"  {stimol_course}")

    # Углеводная дельта под сегодняшнюю сессию
    lines.append("")
    lines.append(_format_carb_advice(scenario))

    lines.append("")
    lines.append("📚 Полный протокол: memory/reference_supplements_protocol.md")
    lines.append("📚 Питание: memory/reference_breakfast_typical.md")
    return "\n".join(lines)


def _format_carb_advice(scenario: str) -> str:
    """Расчёт углеводной дельты под сегодняшнюю сессию.

    Стандартный завтрак: Matti 60г + йогурт 150г + Немолоко 150мл = ~52 г углеводов.
    Целевые углеводы (Семёнов): 3-4 г/кг для длительной/скоростной за 2-3 ч до.
    Body weight = 82 кг → таргет 246-328 г углеводов.
    """
    BODY_WEIGHT = 82
    BREAKFAST_CARBS = 52  # Matti 60 + йогурт 150 + Немолоко 150
    BREAKFAST_PROTEIN = 12

    lines = []
    lines.append("🍳 Питание на сегодня:")
    lines.append(f"  Стандартный завтрак (Matti 60г + йогурт 150г + Немолоко 150мл) = ~{BREAKFAST_CARBS}г углеводов, ~{BREAKFAST_PROTEIN}г белка")

    if scenario == "rest":
        lines.append("  ✅ Стандартный завтрак подходит как есть")
        return "\n".join(lines)

    if scenario == "A":
        # Лёгкая утренняя натощак — завтрак после
        target_protein = round(BODY_WEIGHT * 0.35)
        deficit_protein = max(0, target_protein - BREAKFAST_PROTEIN)
        lines.append(f"  Лёгкая утренняя натощак → завтрак ПОСЛЕ тренировки")
        lines.append(f"  Целевой белок post-workout: {target_protein} г (0.35 г/кг)")
        if deficit_protein > 0:
            lines.append(f"  Стандарт даёт {BREAKFAST_PROTEIN} г → ДОБРАТЬ +{deficit_protein} г белка:")
            lines.append(f"    • 2 яйца (~12 г) ИЛИ творог 100 г (~18 г) ИЛИ протеин 1 ложка (~22 г)")
        return "\n".join(lines)

    # Сценарии B и C — нужны углеводы за 2-3 ч до
    target_min = BODY_WEIGHT * 3  # 246 г
    target_max = BODY_WEIGHT * 4  # 328 г
    deficit = target_min - BREAKFAST_CARBS  # ~194 г

    lines.append(f"  Тренировка тяжёлая → ЗА 2-3 ч до старта целевые углеводы: {target_min}-{target_max} г (3-4 г/кг для 82 кг)")
    lines.append(f"  Дефицит к стандартному: ~{deficit} г углеводов")
    lines.append("")
    lines.append("  📈 Что добавить к завтраку (примеры):")
    lines.append("    • Овсянка 80 г сухая = +50 г углеводов (~280 ккал)")
    lines.append("    • 1 банан = +25 г")
    lines.append("    • Кусок хлеба с мёдом = +30 г")
    lines.append("    • 250 мл сока = +28 г")
    lines.append("    • Спортивный гель = +25 г")
    lines.append("")
    lines.append(f"  💡 Реальный pre-race завтрак: овсянка 80г + 2 банана + хлеб+мёд + стандарт = ~{BREAKFAST_CARBS+50+50+30}г углеводов")

    return "\n".join(lines)


def _check_stimol_course(today_iso: str, sessions: list) -> str:
    """Проверить нужен ли курсовой Стимол по календарю.

    Особые периоды:
    - Тейпер 5-7 дней до B-старта 20.06 → 14-19.06
    - Тейпер 13 дней до A-старта 26.09 → 14-25.09
    - Тейпер 3 дня до 12.06 ночник 2.5К → 09-11.06
    - Микроцикл перегрузка W21 (14-20.09) → ВТ-СР-ПТ интенсивов
    - Восстановительные недели — детектится через тип сессий 'отдых' / 'тонус'
    """
    # Тейпер B-старта 20.06.2026
    if "2026-06-14" <= today_iso <= "2026-06-19":
        return "Тейпер B-старта 20.06: 1-2 пакета × 2 раза в день (антиастеник)"
    # Тейпер ночника 12.06
    if "2026-06-09" <= today_iso <= "2026-06-11":
        return "Тейпер ночника 12.06: 1 пакет × 2 раза в день"
    # Тейпер A-старта 26.09
    if "2026-09-14" <= today_iso <= "2026-09-25":
        return "Тейпер A-старта 26.09: 1-2 пакета × 2 раза в день (главный старт сезона)"
    # Микроцикл перегрузка W21 (14-20.09) — но это и есть тейпер
    # Дни ВТ-СР-ПТ в W21 особо требуют
    if today_iso in ("2026-09-15", "2026-09-16", "2026-09-18"):
        return "W21 микроцикл перегрузка (Вертышев): 2 пакета сегодня, обязательно"
    # Восстановительные недели — общая рекомендация курса
    if any((s.type or "").lower() in ("отдых", "ст-тон") for s in sessions):
        if any("разгрузк" in (s.text or "").lower() or "восст" in (s.text or "").lower() for s in sessions):
            return "Разгрузочный период: можно начать курс 10 дней по 1 пакету × 2-3 раза в день"
    return ""


async def cmd_supps(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Рекомендации БАДов на сегодня по типу тренировки."""
    if not _is_authorized(update):
        return
    today = date.today()
    sessions = plan_reader.for_date(today)
    scenario = _detect_supplement_scenario(sessions)
    text = _format_supplements(scenario, sessions)
    await update.message.reply_text(text)


async def cmd_vo2(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Текущий Garmin VO2max + trend + помесячный прогноз сезона."""
    if not _is_authorized(update):
        return

    from datetime import date, timedelta

    # Forecast hardcoded из reference_vo2max_garmin.md
    forecast = {
        5: ("Май", "55 → 57", "втягивающий, контр.5К 31.05 = +1-2"),
        6: ("Июнь", "57 → 60", "темпы + ночник + Гершлер"),
        7: ("Июль", "59-61", "БМВ блок — стагнация ожидаема"),
        8: ("Август", "61 → 63", "ПАНО + начало МПК"),
        9: ("Сентябрь", "63 → 65", "🏆 пик сезона, А-старт sub-34"),
        10: ("Октябрь", "60-62", "просадка от перехода на лыжи"),
        11: ("Ноябрь", "58-60 (бег)", "лыжный VO2 строится отдельно"),
    }

    with db.get_conn() as conn:
        # Current (latest) VO2max per activity_type
        latest = {}
        for sport in ("running", "cycling"):
            row = conn.execute(
                """SELECT start_time_local, vo2_max FROM activities
                   WHERE athlete_id=? AND activity_type=? AND vo2_max IS NOT NULL
                   ORDER BY start_time_local DESC LIMIT 1""",
                (config.ATHLETE_ID, sport),
            ).fetchone()
            if row:
                latest[sport] = (row["start_time_local"][:10], row["vo2_max"])

        # 30/90 day max for running
        today_iso = date.today().isoformat()
        d30 = (date.today() - timedelta(days=30)).isoformat()
        d90 = (date.today() - timedelta(days=90)).isoformat()

        run_30 = conn.execute(
            """SELECT MAX(vo2_max), MIN(vo2_max), COUNT(vo2_max) FROM activities
               WHERE athlete_id=? AND activity_type='running' AND vo2_max IS NOT NULL
                 AND substr(start_time_local,1,10) >= ?""",
            (config.ATHLETE_ID, d30),
        ).fetchone()

        run_90 = conn.execute(
            """SELECT MAX(vo2_max), MIN(vo2_max) FROM activities
               WHERE athlete_id=? AND activity_type='running' AND vo2_max IS NOT NULL
                 AND substr(start_time_local,1,10) >= ?""",
            (config.ATHLETE_ID, d90),
        ).fetchone()

        # All-time peak
        peak = conn.execute(
            """SELECT MAX(vo2_max), start_time_local FROM activities
               WHERE athlete_id=? AND activity_type='running' AND vo2_max IS NOT NULL""",
            (config.ATHLETE_ID,),
        ).fetchone()

    lines = []
    lines.append("📊 VO2max")
    lines.append("")
    lines.append("Текущий (Garmin):")
    if "running" in latest:
        d, v = latest["running"]
        lines.append(f"  🏃 Бег: {v:.0f} (на {d})")
    if "cycling" in latest:
        d, v = latest["cycling"]
        lines.append(f"  🚴 Вело: {v:.0f} (на {d})")
    lines.append("")

    if run_30 and run_30[2]:
        lines.append(f"Бег за 30 дней: {run_30[1]:.0f}–{run_30[0]:.0f} ({run_30[2]} записей)")
    if run_90 and run_90[0]:
        lines.append(f"Бег за 90 дней: {run_90[1]:.0f}–{run_90[0]:.0f}")
    if peak and peak[0]:
        lines.append(f"Пик беговой: {peak[0]:.0f} (на {peak[1][:10]})")
    lines.append("")

    # Compare with расчётный
    lines.append("Реальный (по vLT2 теста 25.04.2026):")
    lines.append("  Расчёт: ~62-65 (vVO2max=18.5 км/ч)")
    lines.append(f"  Текущий Garmin занижен — артефакт зимнего перерыва")
    lines.append("")

    # Today's month + forecast
    cur_m = date.today().month
    lines.append("📅 Прогноз по месяцам (бег):")
    for m in sorted(forecast.keys()):
        name, val, why = forecast[m]
        marker = "▶ " if m == cur_m else "  "
        lines.append(f"{marker}{name}: {val} — {why}")
    lines.append("")

    lines.append("⚠️ После лактат-теста ~июнь 2026:")
    lines.append("  обновить LTHR в Garmin (сейчас 174, реальный 178)")
    lines.append("  → автоотскок Garmin VO2max +1-3 без улучшения формы")

    await update.message.reply_text("\n".join(lines))


async def cmd_brief(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Бриф(ы) на сегодня — силовая / кор / плиометрика."""
    if not _is_authorized(update):
        return
    today = date.today()
    sessions = plan_reader.for_date(today)
    brief_texts = briefs.for_today(sessions)
    if not brief_texts:
        await update.message.reply_text(
            "На сегодня нет силовых / кор / плиометрических сессий — брифа не будет."
        )
        return
    for t in brief_texts:
        await update.message.reply_text(t)


async def cmd_last(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    if not _is_authorized(update):
        return

    with db.get_conn() as conn:
        row = conn.execute(
            """SELECT a.activity_id, a.start_time_local, a.activity_type,
                      a.duration_sec, a.distance_m, a.avg_hr, a.max_hr,
                      t.plan_text, t.plan_zone, t.actual_zone_time_pct,
                      t.matches_plan, t.raw_assessment_json
               FROM activities a
               LEFT JOIN training_assessment t ON t.activity_id = a.activity_id
               WHERE a.athlete_id=? AND a.duration_sec >= 600
               ORDER BY a.start_time_local DESC LIMIT 1""",
            (config.ATHLETE_ID,),
        ).fetchone()

    if not row:
        await update.message.reply_text("Активностей в БД нет.")
        return

    sport_ru = {
        "running": "бег",
        "cycling": "вело",
        "strength_training": "силовая",
    }.get(row["activity_type"], row["activity_type"])
    dur_min = row["duration_sec"] / 60 if row["duration_sec"] else 0
    dist_km = row["distance_m"] / 1000 if row["distance_m"] else 0

    raw = row["start_time_local"]  # "YYYY-MM-DD HH:MM:SS"
    pretty_dt = f"{raw[8:10]}.{raw[5:7]}.{raw[0:4]} {raw[11:16]}"
    lines = [
        f"📊 Последняя активность: {pretty_dt}",
        f"  {sport_ru}: {dur_min:.0f}м / {dist_km:.2f}км / HR {int(row['avg_hr'] or 0)} avg",
    ]
    if row["plan_text"]:
        lines.append(f"\n📋 План: {row['plan_text']}")
    if row["matches_plan"] == 1:
        lines.append(f"🎯 Соответствие: ✅ {row['actual_zone_time_pct']*100:.0f}% в {row['plan_zone']}")
    elif row["matches_plan"] == 0:
        lines.append(f"🎯 Соответствие: ⚠️ {row['actual_zone_time_pct']*100:.0f}% в {row['plan_zone']}")
    else:
        lines.append("🎯 Соответствие: — (не оценено)")
    await update.message.reply_text("\n".join(lines))


async def cmd_week(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    if not _is_authorized(update):
        return
    today = date.today()
    sessions = plan_reader.for_week_of(today)
    if not sessions:
        await update.message.reply_text("План на неделю не найден.")
        return

    weekday = today.weekday()
    monday = today - timedelta(days=weekday)
    sunday = monday + timedelta(days=6)
    lines = [f"📅 План недели {monday.strftime('%d.%m')}–{sunday.strftime('%d.%m')}:"]
    last_date = None
    total_h = 0.0
    for s in sessions:
        if s.date != last_date:
            # s.date = "YYYY-MM-DD" → выводим как "DD.MM"
            day_part = f"{s.date[8:10]}.{s.date[5:7]}"
            lines.append(f"\n{s.day_short} {day_part}:")
            last_date = s.date
        icon = "☀" if s.part == "утро" else "🌙"
        lines.append(f"  {icon} {s.text}")
        total_h += s.hours
    lines.append(f"\n⏱ Итого: {total_h:.1f} ч")
    await update.message.reply_text("\n".join(lines))


async def cmd_check(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    if not _is_authorized(update):
        return
    await update.message.reply_text("🔄 Дёргаю Garmin sync и проверяю активности...")

    morning.run_garmin_sync()

    # Используем garmin_client из job context (положим в bot_data при старте)
    garmin_client = context.application.bot_data.get("garmin_client")
    chat_id = update.effective_chat.id
    since = (date.today() - timedelta(days=2)).isoformat()
    n = await activity_check.check_and_report(
        bot=context.bot,
        chat_id=chat_id,
        since_date_iso=since,
        garmin_client=garmin_client,
    )
    if n == 0:
        await update.message.reply_text("Новых активностей не найдено.")


def _is_authorized(update: Update) -> bool:
    """Проверка что сообщение от привязанного chat_id."""
    saved = db.get_chat_id()
    if not saved:
        return True  # бот ещё не привязан, /start закрепит
    return str(update.effective_chat.id) == str(saved)


# === Subjective feedback ===

async def on_feedback_callback(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Обработка тапа на кнопку 🔥/👍/😴 под вопросом «как зашло»."""
    query = update.callback_query
    log.info(f"feedback callback received: data={query.data if query else None}")
    if not query or not query.data or not query.data.startswith("feel|"):
        return
    if not _is_authorized(update):
        await query.answer("⛔", show_alert=False)
        return

    try:
        _, aid_str, feeling = query.data.split("|", 2)
        activity_id = int(aid_str)
    except Exception:
        await query.answer("формат сломан", show_alert=False)
        return
    if feeling not in _FEELING_LABEL:
        await query.answer("неизвестная кнопка", show_alert=False)
        return

    db.save_feedback(activity_id, feeling)
    await query.answer(f"Записал: {_FEELING_LABEL[feeling]}", show_alert=False)

    # Снимаем кнопки + добавляем приглашение написать подробно
    try:
        await query.edit_message_reply_markup(reply_markup=None)
        await query.message.reply_text(
            f"✅ {_FEELING_LABEL[feeling]} — записано.\n\n"
            "Если хочешь добавить деталей (что чувствовал, ветер, группа, нога) — "
            "просто ответь следующим сообщением, оно пойдёт в заметки тренировки."
        )
        # Окно для текста: 6 ч от момента тапа
        db.set_pending_text_feedback(
            activity_id=activity_id,
            prompt_message_id=query.message.message_id,
            ttl_hours=6,
        )
    except Exception as e:
        log.warning(f"feedback callback post-update failed: {e}")


async def on_text_feedback(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Роутер свободного текста.

    Если есть pending feedback (после /feel или inline-кнопки) — пишем в notes.
    Иначе применяем эвристику D (jarvis_routing):
      - короткий feel-like текст → молчим (как раньше)
      - вопрос / длинный / содержит триггер → JarvisAgent (Claude API)
    """
    if not update.message or not update.message.text:
        return
    if not _is_authorized(update):
        return
    text = update.message.text.strip()
    if not text or text.startswith("/"):
        return

    pending = db.get_pending_text_feedback()
    if pending:
        activity_id = pending["activity_id"]
        db.save_feedback(activity_id, feeling="manual_text", notes=text)
        db.clear_pending_text_feedback()
        await update.message.reply_text(
            "📝 Записал в заметки тренировки. Учту при следующем анализе и в воскресном дайджесте."
        )
        return

    # Нет pending — применяем D-эвристику
    if not jarvis_routing.is_jarvis_query(text):
        # Короткий feel-like без триггера и без pending feedback —
        # не понимаем что с ним делать, молчим (старое поведение).
        return

    await _handle_jarvis_query(update, context, text)


async def _handle_jarvis_query(
    update: Update, context: ContextTypes.DEFAULT_TYPE, text: str
) -> None:
    """Передаём вопрос в JarvisAgent, отправляем ответ кусками."""
    chat_id = update.effective_chat.id
    try:
        await context.bot.send_chat_action(chat_id=chat_id, action="typing")
    except Exception:
        pass

    try:
        agent = _get_jarvis()
    except Exception as exc:
        log.exception("Jarvis init failed: %s", exc)
        await update.message.reply_text(f"⚠️ Jarvis не запускается: {exc}")
        return

    try:
        answer = await agent.query_async(chat_id, text)
    except Exception as exc:
        log.exception("Jarvis query failed: %s", exc)
        await update.message.reply_text(f"⚠️ Ошибка Jarvis: {exc}")
        return

    if not answer:
        await update.message.reply_text("(пустой ответ)")
        return

    # Режем длинный ответ на куски
    for i in range(0, len(answer), _TG_CHUNK):
        chunk = answer[i : i + _TG_CHUNK]
        try:
            await update.message.reply_text(chunk)
        except Exception as exc:
            log.warning("send chunk failed: %s", exc)


async def cmd_jarvis_reset(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Очистить thread с Jarvis (новая беседа с чистого листа)."""
    if not _is_authorized(update):
        return
    try:
        agent = _get_jarvis()
        agent.reset_thread(update.effective_chat.id)
        await update.message.reply_text("🔄 Контекст Jarvis сброшен. Начинаем заново.")
    except Exception as exc:
        await update.message.reply_text(f"⚠️ {exc}")


async def cmd_jarvis_spend(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Сколько потрачено на Anthropic API сегодня."""
    if not _is_authorized(update):
        return
    try:
        from . import jarvis_agent as _ja
        spend = _ja.today_spend_usd()
        limit = _ja.MAX_DAILY_USD
        await update.message.reply_text(
            f"💰 Anthropic API сегодня: ${spend:.4f} / лимит ${limit:.2f}\n"
            f"Модель: {_ja.MODEL}"
        )
    except Exception as exc:
        await update.message.reply_text(f"⚠️ {exc}")


async def cmd_digest(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Воскресный недельный дайджест по требованию (для теста и не только)."""
    if not _is_authorized(update):
        return
    chat_id = update.effective_chat.id
    try:
        await weekly_digest.send_weekly_digest(context.bot, chat_id)
    except Exception as e:
        log.exception(f"weekly digest failed: {e}")
        await update.message.reply_text(f"Дайджест упал: {e}")


async def cmd_feel(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Ручной фидбек на последнюю активность.
    Формат:
        /feel огонь  — короткое
        /feel тяжко колено побаливало, темп не тянул
        /feel  — без аргументов: открывает окно текстового ответа на 6 ч
    """
    if not _is_authorized(update):
        return

    aid = db.last_unansweredable_activity(config.ATHLETE_ID, limit_hours=36)
    if not aid:
        await update.message.reply_text("Не нашёл свежей активности (за 36 ч).")
        return

    args = " ".join(context.args).strip() if context.args else ""
    if not args:
        db.set_pending_text_feedback(
            activity_id=aid,
            prompt_message_id=update.message.message_id,
            ttl_hours=6,
        )
        await update.message.reply_text(
            f"Жду текст про последнюю тренировку (id {aid}). "
            "Пиши свободно следующим сообщением — оно пойдёт в заметки."
        )
        return

    # Распарсим первый токен на feeling
    parts = args.split(maxsplit=1)
    head = parts[0].lower()
    feeling_map = {
        "огонь": "fire", "fire": "fire", "🔥": "fire",
        "норм": "normal", "ок": "normal", "ok": "normal", "👍": "normal",
        "тяжко": "tired", "устал": "tired", "tired": "tired", "😴": "tired",
    }
    feeling = feeling_map.get(head)
    notes = parts[1] if len(parts) > 1 else None
    if feeling is None:
        # Считаем весь аргумент текстом-описанием
        feeling = "manual_text"
        notes = args

    db.save_feedback(aid, feeling=feeling, notes=notes)
    label = _FEELING_LABEL.get(feeling, "📝 текст")
    suffix = f"\n«{notes}»" if notes else ""
    await update.message.reply_text(
        f"✅ Записал к активности {aid}: {label}{suffix}"
    )
