"""
Extract numeric / protocol-relevant snippets from each article.
Strategy: find every line that contains numbers OR specific Russian keywords;
output as a transliterated dump that survives the broken terminal.
"""
import os
import re

base = r'C:\1с_dev\garmin_analytics\analysis_temp'
files = [
    'combining_aerobic_strength_body.txt',
    'short_program_aerobic_anaerobic_body.txt',
    'planning_xc_skiers_body.txt',
    'short_intervals_body.txt',
    'muscle_function_cyclic_body.txt',
]

# Russian-to-Latin transliteration so output prints in our terminal
TR = {
    'а':'a','б':'b','в':'v','г':'g','д':'d','е':'e','ё':'yo','ж':'zh','з':'z','и':'i',
    'й':'y','к':'k','л':'l','м':'m','н':'n','о':'o','п':'p','р':'r','с':'s','т':'t',
    'у':'u','ф':'f','х':'kh','ц':'ts','ч':'ch','ш':'sh','щ':'sch','ъ':'','ы':'y','ь':"'",
    'э':'e','ю':'yu','я':'ya',
    'А':'A','Б':'B','В':'V','Г':'G','Д':'D','Е':'E','Ё':'Yo','Ж':'Zh','З':'Z','И':'I',
    'Й':'Y','К':'K','Л':'L','М':'M','Н':'N','О':'O','П':'P','Р':'R','С':'S','Т':'T',
    'У':'U','Ф':'F','Х':'Kh','Ц':'Ts','Ч':'Ch','Ш':'Sh','Щ':'Sch','Ъ':'','Ы':'Y','Ь':"'",
    'Э':'E','Ю':'Yu','Я':'Ya',
}

def translit(s):
    return ''.join(TR.get(c, c) for c in s)

# Patterns: any number, percent, %МПС, sec, min, повт, серий, etc.
NUM_PAT = re.compile(r'\d')

# Keywords (russian) that signal training-protocol relevant content
KW = [
    'МПС','МПК','ПАНО','АнП','АэП','ОМВ','ММВ','БМВ','ЧСС','HR','ЧССmax',
    'мин','сек','секунд','минут','час',
    'повтор','серий','серии','подход','подходов',
    'недел','микроцикл','мезоцикл','макроцикл','блок',
    'отдых','интервал','прыж','прыжк','ускорен','спринт',
    'силов','аэробн','анаэробн','гипертроф','стато',
    'отказ','отказа',
    'процент','%',
    'неделя','день','дней',
    'в зоне','зона','тренировк','подготовк',
    '%МПС','% МПС','% от','% МПК','% ЧСС',
    'РМ','лактат',
    'эксперимент','протокол','схема','план','цикл',
    'апрель','май','июнь','июль','август','сентябрь','октябрь','ноябрь','декабрь','январь','февраль','март',
    'старт','соревнован',
    'Шишкин','Мякинч','Вертыш','Селуянов','Монахов','Ткачук','Rodas',
]

OUT = []

for f in files:
    p = os.path.join(base, f)
    with open(p, 'r', encoding='utf-8') as fh:
        text = fh.read()
    OUT.append('\n' + '=' * 80)
    OUT.append('FILE: ' + f)
    OUT.append('=' * 80)
    paragraphs = re.split(r'\n\s*\n', text)
    for i, par in enumerate(paragraphs):
        par_clean = par.strip()
        if not par_clean:
            continue
        # Skip obvious nav junk: lines that are < 4 chars long and lots of placeholders
        if len(par_clean) < 4:
            continue
        has_num = bool(NUM_PAT.search(par_clean))
        has_kw = any(k.lower() in par_clean.lower() for k in KW)
        if not (has_num or has_kw):
            continue
        # Skip if paragraph is mostly menu hits (Latin letters only)
        if all(c.isascii() and not c.isdigit() for c in par_clean):
            continue
        OUT.append(f'\n[par {i}]')
        OUT.append(translit(par_clean))

out_p = r'C:\1с_dev\garmin_analytics\analysis_temp\findings_translit.txt'
with open(out_p, 'w', encoding='utf-8') as oh:
    oh.write('\n'.join(OUT))

print('Wrote:', out_p, 'lines:', len(OUT))
