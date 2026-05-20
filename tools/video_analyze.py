"""
Анализ видео для последующего разбора Claude.

Использование:
    python tools/video_analyze.py <путь_к_видео_или_youtube_url> [--out DIR] [--frames-every N]

Что делает:
    1. Если URL — скачивает через yt-dlp в DIR/source.<ext>.
    2. ffmpeg извлекает аудио (mono 16kHz wav) и кадры (1 кадр в N секунд).
    3. faster-whisper транскрибирует аудио с таймкодами.
    4. Складывает в DIR:
        - transcript.txt (read-friendly)
        - transcript.json (сегменты с тайминами)
        - frames/frame_HHMMSS.jpg
        - meta.json (длительность, язык, число кадров)

После этого Claude может прочитать transcript.txt и часть кадров и сделать выжимку.
"""
from __future__ import annotations

import argparse
import json
import shutil
import subprocess
import sys
from datetime import timedelta
from pathlib import Path


def run(cmd: list[str], **kw) -> subprocess.CompletedProcess:
    return subprocess.run(cmd, check=True, **kw)


def find_ffmpeg() -> str:
    if shutil.which("ffmpeg"):
        return "ffmpeg"
    candidates = list(
        Path("C:/Users/akhak/AppData/Local/Microsoft/WinGet/Packages").glob(
            "*FFmpeg*/**/bin/ffmpeg.exe"
        )
    )
    if candidates:
        return str(candidates[0])
    raise RuntimeError("ffmpeg не найден ни в PATH, ни в WinGet Packages")


def is_url(s: str) -> bool:
    return s.startswith("http://") or s.startswith("https://")


def download_youtube(url: str, dest_dir: Path) -> Path:
    out_template = dest_dir / "source.%(ext)s"
    run(
        [
            "yt-dlp",
            "-f",
            "bv*[height<=720]+ba/b[height<=720]",
            "--merge-output-format",
            "mp4",
            "-o",
            str(out_template),
            url,
        ]
    )
    files = list(dest_dir.glob("source.*"))
    if not files:
        raise RuntimeError("yt-dlp ничего не скачал")
    return files[0]


def extract_audio(ffmpeg: str, video: Path, dest: Path) -> None:
    run(
        [
            ffmpeg,
            "-y",
            "-i",
            str(video),
            "-vn",
            "-ac",
            "1",
            "-ar",
            "16000",
            "-c:a",
            "pcm_s16le",
            str(dest),
        ],
        stdout=subprocess.DEVNULL,
        stderr=subprocess.DEVNULL,
    )


def extract_frames(ffmpeg: str, video: Path, dest_dir: Path, every_seconds: int) -> int:
    dest_dir.mkdir(parents=True, exist_ok=True)
    pattern = str(dest_dir / "frame_%05d.jpg")
    run(
        [
            ffmpeg,
            "-y",
            "-i",
            str(video),
            "-vf",
            f"fps=1/{every_seconds},scale=640:-1",
            "-q:v",
            "3",
            pattern,
        ],
        stdout=subprocess.DEVNULL,
        stderr=subprocess.DEVNULL,
    )
    frames = sorted(dest_dir.glob("frame_*.jpg"))
    for i, f in enumerate(frames):
        seconds = i * every_seconds
        new_name = dest_dir / f"frame_{seconds // 3600:02d}{(seconds % 3600) // 60:02d}{seconds % 60:02d}.jpg"
        f.rename(new_name)
    return len(frames)


def transcribe(audio: Path, model_size: str = "base") -> tuple[list[dict], str, float]:
    from faster_whisper import WhisperModel

    print(f"  загружаю модель faster-whisper ({model_size})...", file=sys.stderr)
    model = WhisperModel(model_size, device="cpu", compute_type="int8")
    print("  транскрибирую...", file=sys.stderr)
    segments, info = model.transcribe(str(audio), beam_size=1, vad_filter=True)
    out: list[dict] = []
    for seg in segments:
        out.append(
            {
                "start": round(seg.start, 2),
                "end": round(seg.end, 2),
                "text": seg.text.strip(),
            }
        )
    return out, info.language, info.duration


def fmt_ts(seconds: float) -> str:
    return str(timedelta(seconds=int(seconds)))


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("source", help="Путь к видеофайлу или YouTube URL")
    ap.add_argument("--out", default="video_analysis", help="Папка для результатов")
    ap.add_argument(
        "--frames-every", type=int, default=30, help="1 кадр каждые N секунд (default 30)"
    )
    ap.add_argument(
        "--whisper-model",
        default="base",
        choices=["tiny", "base", "small", "medium", "large-v3"],
        help="Модель faster-whisper (default base, ~150 MB)",
    )
    args = ap.parse_args()

    out_dir = Path(args.out)
    out_dir.mkdir(parents=True, exist_ok=True)

    ffmpeg = find_ffmpeg()
    print(f"ffmpeg: {ffmpeg}", file=sys.stderr)

    if is_url(args.source):
        print(f"скачиваю {args.source}...", file=sys.stderr)
        video = download_youtube(args.source, out_dir)
    else:
        video = Path(args.source)
        if not video.exists():
            print(f"файл не найден: {video}", file=sys.stderr)
            return 2

    audio = out_dir / "audio.wav"
    print("извлекаю аудио...", file=sys.stderr)
    extract_audio(ffmpeg, video, audio)

    print(f"нарезаю кадры (1 в {args.frames_every} с)...", file=sys.stderr)
    frame_count = extract_frames(ffmpeg, video, out_dir / "frames", args.frames_every)

    print("транскрибирую...", file=sys.stderr)
    segments, language, duration = transcribe(audio, args.whisper_model)

    (out_dir / "transcript.json").write_text(
        json.dumps(segments, ensure_ascii=False, indent=2), encoding="utf-8"
    )

    lines = [f"[{fmt_ts(s['start'])}] {s['text']}" for s in segments]
    (out_dir / "transcript.txt").write_text("\n".join(lines), encoding="utf-8")

    meta = {
        "source": args.source,
        "video_file": str(video.name),
        "duration_seconds": round(duration, 1),
        "duration_human": fmt_ts(duration),
        "language": language,
        "frame_count": frame_count,
        "frames_every_seconds": args.frames_every,
        "whisper_model": args.whisper_model,
        "segments": len(segments),
    }
    (out_dir / "meta.json").write_text(
        json.dumps(meta, ensure_ascii=False, indent=2), encoding="utf-8"
    )

    print("\n=== готово ===", file=sys.stderr)
    print(json.dumps(meta, ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    sys.exit(main())
