"""
Extract body of each Triskirun article and save as clean .md.
The .txt files have menu chrome at the top and bottom; we want the article body only.
"""
import os
import re

base = r'C:\1с_dev\garmin_analytics\knowledge\articles\triskirun'
out_dir = r'C:\1с_dev\garmin_analytics\analysis_temp'
os.makedirs(out_dir, exist_ok=True)

files = [
    'combining_aerobic_strength.txt',
    'short_program_aerobic_anaerobic.txt',
    'planning_xc_skiers.txt',
    'short_intervals.txt',
    'muscle_function_cyclic.txt',
]

# Markers that bracket the article body in the .txt dumps:
# Article body starts shortly after the title (after "Share on Twitter" line).
# It ends near "Training" or "Hot" navigation footer.

start_markers = [
    'Share on Twitter',
    'Share on Pinterest',
]
end_markers = [
    'Training похожие материалы',
    'Training похожие',
    'Похожие материалы',
    'похожие материалы',
    'Подпишитесь на нашу рассылку',
    'Похожие',
    'Источник материала:',  # right before footer in some
]

for f in files:
    p = os.path.join(base, f)
    with open(p, 'rb') as fh:
        text = fh.read().decode('utf-8', errors='replace')

    # Find the start: take everything after second occurrence of title or after Share on Twitter
    start_idx = -1
    for m in start_markers:
        idx = text.find(m)
        if idx > 0:
            start_idx = idx + len(m)
            break
    if start_idx < 0:
        start_idx = 0

    # End at first nav-footer marker
    body = text[start_idx:]
    end_idx = len(body)
    for m in end_markers:
        idx = body.find(m)
        if 0 < idx < end_idx:
            end_idx = idx
    body = body[:end_idx]

    # Compress whitespace
    lines = []
    blank = 0
    for ln in body.split('\n'):
        s = ln.strip()
        if not s:
            blank += 1
            if blank <= 1:
                lines.append('')
            continue
        blank = 0
        lines.append(s)
    cleaned = '\n'.join(lines).strip()

    out_p = os.path.join(out_dir, f.replace('.txt', '_body.txt'))
    with open(out_p, 'w', encoding='utf-8') as oh:
        oh.write(cleaned)
    print(f, '->', out_p, 'chars:', len(cleaned))
