"""Снять скриншот локального дашборда через playwright (headless chromium).

Использование:
  .venv/Scripts/python.exe tools/dashboard_screenshot.py [URL] [OUT_PATH]

Дефолты:
  URL      = http://127.0.0.1:8501
  OUT_PATH = docs/screenshots/dashboard-<timestamp>.png

После запуска возвращает путь к PNG, его можно прочитать через Read tool.
"""
from __future__ import annotations

import sys
import time
from pathlib import Path

from playwright.sync_api import sync_playwright

URL_DEFAULT = "http://127.0.0.1:8501"
OUT_DIR = Path(__file__).parent.parent / "docs" / "screenshots"


def shoot(url: str, out: Path, viewport=(1280, 900), full_page: bool = True,
          wait_seconds: float = 4.0) -> Path:
    out.parent.mkdir(parents=True, exist_ok=True)
    with sync_playwright() as p:
        browser = p.chromium.launch(headless=True)
        ctx = browser.new_context(viewport={"width": viewport[0], "height": viewport[1]})
        page = ctx.new_page()
        page.goto(url, wait_until="networkidle", timeout=20_000)
        # Streamlit рендерится в несколько проходов — дать время на CSS-инъекцию.
        time.sleep(wait_seconds)
        page.screenshot(path=str(out), full_page=full_page)
        browser.close()
    return out


if __name__ == "__main__":
    url = sys.argv[1] if len(sys.argv) > 1 else URL_DEFAULT
    if len(sys.argv) > 2:
        out = Path(sys.argv[2])
    else:
        ts = time.strftime("%Y%m%d-%H%M%S")
        out = OUT_DIR / f"dashboard-{ts}.png"
    result = shoot(url, out)
    print(f"OK: {result.resolve()}")
