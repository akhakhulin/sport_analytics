"""
Визуализация: данные лактатного теста vs зоны в 4 системах
(Garmin / лактат-калиброванные / тренерская таблица %HRmax / Федосеев 2023).
"""
from __future__ import annotations

from pathlib import Path

import matplotlib.pyplot as plt
import matplotlib.patches as patches

OUT = Path(__file__).resolve().parents[1] / "knowledge" / "protocols" / "zones_comparison_2026-04-25.png"

# Тестовые данные (12.5 км/ч исправлено на 1.55 — глюк лактометра)
TEST = [
    # km/h, mmol, HR
    (9.5,  1.2,  124),
    (10.5, 1.3,  131),
    (11.5, 1.7,  141),
    (12.0, 1.8,  144),
    (12.5, 1.55, 149),
    (13.0, 1.7,  153),
    (13.5, 1.9,  158),
    (14.0, 2.7,  162),
    (15.0, 2.4,  169),
    (16.0, 3.2,  175),
    (16.5, 4.6,  181),
]

# Зоны: (название, [границы Z1..Z5 верхние])
# Структура: Z1 = [floor, Z1_ceil], Z2 = [Z1_ceil, Z2_ceil], ...
ZONE_SYSTEMS = {
    "Garmin RUNNING": [110, 134, 154, 164, 171, 187],
    "Лактат-калибр (рекоменд.)": [110, 139, 161, 178, 185, 187],
    "Тренер %HRmax (Hmax=187)": [110, 134, 153, 163, 172, 187],
    "Федосеев 2023": [110, 139, 161, 176, 181, 187],
}

# Цвета зон по тренерской таблице (зелён→жёлт→красн)
ZONE_COLORS = ["#a8e063", "#56ab2f", "#fce700", "#ff8c00", "#e63946"]
ZONE_LABELS = ["Z1", "Z2", "Z3", "Z4", "Z5"]


def main():
    fig = plt.figure(figsize=(11, 9))
    gs = fig.add_gridspec(2, 1, height_ratios=[3, 2], hspace=0.4)
    ax1 = fig.add_subplot(gs[0])
    ax2 = fig.add_subplot(gs[1])

    # ───── Top: лактат vs HR с точками теста ─────
    hrs = [t[2] for t in TEST]
    lacts = [t[1] for t in TEST]
    speeds = [t[0] for t in TEST]

    ax1.plot(hrs, lacts, "o-", color="#1f77b4", linewidth=2, markersize=8, zorder=10)
    for hr, lact, sp in TEST:
        ax1.annotate(
            f"{sp}\n{lact}",
            (hr, lact),
            xytext=(0, 10), textcoords="offset points",
            ha="center", fontsize=8, zorder=11,
        )

    # Горизонтальные линии лактатных порогов
    for y, label in [(1.5, "1.5"), (2.5, "2.5"), (4.0, "4.0=ВЛ")]:
        ax1.axhline(y, color="grey", linestyle=":", linewidth=1, alpha=0.6)
        ax1.text(112, y + 0.05, label, fontsize=8, color="grey")

    ax1.set_ylabel("Лактат, ммоль/л", fontsize=11)
    ax1.set_xlim(110, 190)
    ax1.set_ylim(0, 5.5)
    ax1.set_title(
        "Лактатный тест на дорожке (2026-04-25) с наложенными зонами 4 систем",
        fontsize=12, fontweight="bold",
    )
    ax1.grid(True, alpha=0.3)
    ax1.set_xlabel("ЧСС, уд/мин")

    # Маркируем LT1 и LT2
    ax1.axvline(160, color="green", linestyle="--", linewidth=1.5, alpha=0.7)
    ax1.text(160, 5.2, " LT1 / АэП = 160", color="green", fontsize=9, fontweight="bold")
    ax1.axvline(178, color="red", linestyle="--", linewidth=1.5, alpha=0.7)
    ax1.text(178, 5.2, " LT2 / ВЛ = 178", color="red", fontsize=9, fontweight="bold")

    # ───── Bottom: 4 зонные системы как горизонтальные ленты ─────
    n = len(ZONE_SYSTEMS)
    yticks_pos = []
    yticks_labels = []
    bar_h = 0.75
    for i, (name, edges) in enumerate(ZONE_SYSTEMS.items()):
        y_top = n - i - 1
        for z in range(5):
            left, right = edges[z], edges[z + 1]
            if right <= left:
                continue
            rect = patches.Rectangle(
                (left, y_top), right - left, bar_h,
                linewidth=0.8, edgecolor="white",
                facecolor=ZONE_COLORS[z], alpha=0.85,
            )
            ax2.add_patch(rect)
            mid = (left + right) / 2
            ax2.text(
                mid, y_top + bar_h / 2, ZONE_LABELS[z],
                ha="center", va="center",
                fontsize=9, fontweight="bold", color="black",
            )
        yticks_pos.append(y_top + bar_h / 2)
        yticks_labels.append(name)

    # Точки теста — вертикальные пунктиры через все ленты
    for hr, lact, sp in TEST:
        ax2.axvline(hr, ymin=0.05, ymax=0.95,
                    color="#1f77b4", linewidth=0.7, alpha=0.4, linestyle=":")

    ax2.set_xlim(110, 190)
    ax2.set_ylim(-0.2, n)
    ax2.set_yticks(yticks_pos)
    ax2.set_yticklabels(yticks_labels, fontsize=10)
    ax2.set_xlabel("ЧСС, уд/мин", fontsize=11)
    ax2.spines[["top", "right"]].set_visible(False)
    ax2.grid(True, axis="x", alpha=0.3)
    ax2.set_title("Зоны 4-х систем по ЧСС (пунктиры — ступени теста)",
                  fontsize=11)

    # Вертикали LT1/LT2 продолжаем
    ax2.axvline(160, color="green", linestyle="--", linewidth=1.5, alpha=0.5)
    ax2.axvline(178, color="red", linestyle="--", linewidth=1.5, alpha=0.5)

    plt.savefig(OUT, dpi=120, bbox_inches="tight")
    print(f"Сохранено: {OUT}")


if __name__ == "__main__":
    main()
