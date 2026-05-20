"""Объединение двух активностей Garmin в одну (через TCX).

Использование:
    python tools/merge_activities.py <activity_id_1> <activity_id_2>

Что делает:
1. Скачивает обе как TCX (download_activity)
2. Сдвигает timestamps второй активности вплотную к концу первой
3. Сдвигает кумулятивные дистанции второй активности на длину первой
4. Конкатенирует Lap-сегменты в одну Activity
5. Сохраняет в tmp/merged_<id1>_<id2>.tcx
6. Загружает в Garmin (upload_activity)
7. Оригиналы НЕ удаляет (опция --delete-originals)

Замечания:
- TCX — XML с UTC временами в ISO формате
- DistanceMeters внутри Trackpoint — кумулятивные (растут от 0 в начале до total в конце)
- Lap.DistanceMeters — per-lap (не нужно сдвигать)
- Garmin при загрузке TCX пересчитает session/lap summary; основное — правильные track-points
"""
from __future__ import annotations

import argparse
import logging
import os
import sys
from datetime import datetime, timedelta
from pathlib import Path
from lxml import etree as ET

# Подключаем тот же стек что и garmin_sync.py
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
from dotenv import load_dotenv  # noqa: E402

load_dotenv()

from garminconnect import Garmin  # noqa: E402
from garmin_sync import init_client  # noqa: E402


logging.basicConfig(level=logging.INFO, format="%(asctime)s | %(levelname)s | %(message)s")
log = logging.getLogger("merge_activities")

# TCX namespace
TCX_NS = "http://www.garmin.com/xmlschemas/TrainingCenterDatabase/v2"


def parse_iso_utc(s: str) -> datetime:
    """Парсит '2026-05-16T07:05:38.000Z' → datetime."""
    if s.endswith("Z"):
        s = s[:-1]
    return datetime.fromisoformat(s)


def format_iso_utc(dt: datetime) -> str:
    """datetime → '2026-05-16T07:05:38.000Z'."""
    return dt.isoformat(timespec="milliseconds") + "Z"


def download_tcx(client: Garmin, activity_id: int, out_dir: Path) -> Path:
    out = out_dir / f"{activity_id}.tcx"
    if out.exists():
        log.info(f"{activity_id}: уже скачан → {out}")
        return out
    log.info(f"{activity_id}: скачиваю TCX...")
    data = client.download_activity(str(activity_id), dl_fmt=Garmin.ActivityDownloadFormat.TCX)
    out.write_bytes(data)
    log.info(f"{activity_id}: сохранён {len(data)} байт → {out}")
    return out


def get_lap_end_state(activity_elem) -> tuple[datetime, float]:
    """Возвращает (время последней Trackpoint, кумулятивная дистанция)."""
    last_time = None
    last_dist = 0.0
    for tp in activity_elem.iter(f"{{{TCX_NS}}}Trackpoint"):
        t = tp.find(f"{{{TCX_NS}}}Time")
        if t is not None and t.text:
            last_time = parse_iso_utc(t.text)
        d = tp.find(f"{{{TCX_NS}}}DistanceMeters")
        if d is not None and d.text:
            try:
                last_dist = float(d.text)
            except ValueError:
                pass
    if last_time is None:
        raise RuntimeError("Не найдено Trackpoint с Time в activity")
    return last_time, last_dist


def shift_activity(activity_elem, time_shift: timedelta, distance_offset: float) -> None:
    """Сдвигает все Time и DistanceMeters внутри Trackpoint, плюс Lap.StartTime."""
    # Lap.StartTime
    for lap in activity_elem.iter(f"{{{TCX_NS}}}Lap"):
        st = lap.get("StartTime")
        if st:
            new_t = parse_iso_utc(st) + time_shift
            lap.set("StartTime", format_iso_utc(new_t))
    # Trackpoints
    for tp in activity_elem.iter(f"{{{TCX_NS}}}Trackpoint"):
        t = tp.find(f"{{{TCX_NS}}}Time")
        if t is not None and t.text:
            new_t = parse_iso_utc(t.text) + time_shift
            t.text = format_iso_utc(new_t)
        d = tp.find(f"{{{TCX_NS}}}DistanceMeters")
        if d is not None and d.text:
            try:
                cur = float(d.text)
                d.text = f"{cur + distance_offset}"
            except ValueError:
                pass


def merge_tcx(path1: Path, path2: Path, out_path: Path) -> None:
    """Сливает path2 в path1 (вплотную к концу) → out_path."""
    tree1 = ET.parse(path1)
    tree2 = ET.parse(path2)
    root1 = tree1.getroot()
    root2 = tree2.getroot()

    # Находим Activity в обоих
    activities1 = root1.find(f"{{{TCX_NS}}}Activities")
    activities2 = root2.find(f"{{{TCX_NS}}}Activities")
    if activities1 is None or activities2 is None:
        raise RuntimeError("Не найдено <Activities> в одном из TCX")

    act1 = activities1.find(f"{{{TCX_NS}}}Activity")
    act2 = activities2.find(f"{{{TCX_NS}}}Activity")
    if act1 is None or act2 is None:
        raise RuntimeError("Не найдено <Activity> в одном из TCX")

    # Конечное состояние первой
    end_time_1, end_dist_1 = get_lap_end_state(act1)
    log.info(f"Конец первой активности: time={end_time_1}, dist={end_dist_1:.1f} м")

    # Начальное время второй
    first_tp_2 = next(act2.iter(f"{{{TCX_NS}}}Trackpoint"), None)
    if first_tp_2 is None:
        raise RuntimeError("В второй активности нет Trackpoint")
    start_t = first_tp_2.find(f"{{{TCX_NS}}}Time")
    if start_t is None or start_t.text is None:
        raise RuntimeError("Первый Trackpoint без Time")
    start_time_2 = parse_iso_utc(start_t.text)
    log.info(f"Старт второй активности: {start_time_2}")

    # Сдвигаем второй: чтобы её первый Trackpoint совпал по времени с концом первого + 1 сек
    time_shift = end_time_1 + timedelta(seconds=1) - start_time_2
    log.info(f"Сдвиг времени второй активности: {time_shift.total_seconds():.1f} сек")
    shift_activity(act2, time_shift, end_dist_1)

    # Переносим все Lap из act2 в act1
    laps_to_append = list(act2.findall(f"{{{TCX_NS}}}Lap"))
    log.info(f"Переношу {len(laps_to_append)} Lap из второй в первую")
    for lap in laps_to_append:
        act1.append(lap)

    # Перенесём также Creator если у первой нет (опционально)
    creator1 = act1.find(f"{{{TCX_NS}}}Creator")
    creator2 = act2.find(f"{{{TCX_NS}}}Creator")
    if creator1 is None and creator2 is not None:
        act1.append(creator2)

    # Записываем
    tree1.write(out_path, xml_declaration=True, encoding="UTF-8")
    log.info(f"Merged → {out_path} ({out_path.stat().st_size} байт)")


def main() -> None:
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument("activity_id_1", type=int)
    p.add_argument("activity_id_2", type=int)
    p.add_argument("--no-upload", action="store_true", help="Только склеить, не загружать")
    p.add_argument(
        "--delete-originals",
        action="store_true",
        help="После успешной загрузки удалить оригиналы в Garmin",
    )
    args = p.parse_args()

    tmp_dir = Path(__file__).resolve().parent.parent / "tmp"
    tmp_dir.mkdir(exist_ok=True)

    # Логин Garmin
    email = os.environ.get("GARMIN_EMAIL", "")
    password = os.environ.get("GARMIN_PASSWORD", "")
    tokens_dir = os.environ.get("GARMIN_TOKENS_DIR", os.path.expanduser("~/.garminconnect"))
    client = init_client(email, password, tokens_dir)
    log.info("Garmin клиент готов")

    # Скачиваем
    path1 = download_tcx(client, args.activity_id_1, tmp_dir)
    path2 = download_tcx(client, args.activity_id_2, tmp_dir)

    # Сливаем
    out_path = tmp_dir / f"merged_{args.activity_id_1}_{args.activity_id_2}.tcx"
    merge_tcx(path1, path2, out_path)

    if args.no_upload:
        log.info("--no-upload → пропускаю загрузку. Файл готов.")
        return

    # Загружаем
    log.info(f"Загружаю в Garmin: {out_path}...")
    try:
        result = client.upload_activity(str(out_path))
        log.info(f"Ответ Garmin: {result}")
        log.info("✅ Загрузка завершена.")
    except Exception as e:
        log.error(f"Загрузка упала: {e}")
        log.info(f"Merged-файл лежит здесь: {out_path} — можно залить вручную через Garmin Connect.")
        sys.exit(1)

    if args.delete_originals:
        for aid in (args.activity_id_1, args.activity_id_2):
            try:
                client.delete_activity(str(aid))
                log.info(f"Оригинал {aid} удалён")
            except Exception as e:
                log.warning(f"Не удалил {aid}: {e}")


if __name__ == "__main__":
    main()
