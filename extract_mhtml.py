"""
Extract article body from each .mhtml file in triskirun/ using BeautifulSoup.
"""
import os
import re
import email
from email import policy
from bs4 import BeautifulSoup

base = r'C:\1с_dev\garmin_analytics\knowledge\articles\triskirun'
out_dir = r'C:\1с_dev\garmin_analytics\analysis_temp'
os.makedirs(out_dir, exist_ok=True)

SLUGS = {
    'kak-pravilno-sovmeshhat': 'combining_aerobic_strength',
    'korotkaya-trenirovochnaya': 'short_program_aerobic_anaerobic',
    'planirovanie-spetsialnoj': 'planning_xc_skiers',
    '12117-20200616': 'short_intervals',
    'kontseptsiya-vospitaniya': 'muscle_function_cyclic',
}

TR = {
    'а':'a','б':'b','в':'v','г':'g','д':'d','е':'e','ё':'yo','ж':'zh','з':'z','и':'i',
    'й':'y','к':'k','л':'l','м':'m','н':'n','о':'o','п':'p','р':'r','с':'s','т':'t',
    'у':'u','ф':'f','х':'kh','ц':'ts','ч':'ch','ш':'sh','щ':'sch','ъ':'','ы':'y','ь':"'",
    'э':'e','ю':'yu','я':'ya',
    'А':'A','Б':'B','В':'V','Г':'G','Д':'D','Е':'E','Ё':'Yo','Ж':'Zh','З':'Z','И':'I',
    'Й':'Y','К':'K','Л':'L','М':'M','Н':'N','О':'O','П':'P','Р':'R','С':'S','Т':'T',
    'У':'U','Ф':'F','Х':'Kh','Ц':'Ts','Ч':'Ch','Ш':'Sh','Щ':'Sch','Ъ':'','Ы':'Y','Ь':"'",
    'Э':'E','Ю':'Yu','Я':'Ya',
    '«':'"','»':'"','“':'"','”':'"','„':'"','’':"'",
    '—':'-','–':'-','−':'-',
    '…':'...','№':'No.',
    ' ':' ','​':'',
}

def translit(s):
    return ''.join(TR.get(c, c) for c in s)


def parse_mhtml(path):
    with open(path, 'rb') as f:
        msg = email.message_from_binary_file(f, policy=policy.default)
    for part in msg.walk():
        if part.get_content_type() == 'text/html':
            payload = part.get_payload(decode=True)
            charset = part.get_content_charset() or 'utf-8'
            try:
                return payload.decode(charset, errors='replace')
            except Exception:
                return payload.decode('utf-8', errors='replace')
    return None


def extract_article_text(html):
    soup = BeautifulSoup(html, 'lxml')

    # Remove unwanted tags entirely
    for tag in soup(['script','style','nav','footer','aside','header','svg','iframe','noscript','form','button','select','input']):
        tag.decompose()

    # Try to find article content - common WordPress patterns
    candidates = [
        soup.find('article'),
        soup.find('div', class_='entry-content'),
        soup.find('div', class_='post-content'),
        soup.find('div', class_='content'),
        soup.find('main'),
    ]
    article = None
    for c in candidates:
        if c is not None:
            article = c
            break

    if article is None:
        # Fallback: take all <p> tags
        article = soup

    # Extract text from paragraph-level elements only
    paragraphs = []
    for el in article.find_all(['p','h1','h2','h3','h4','h5','li','td','blockquote']):
        # Skip if descendant of removed sections (not relevant since we decomposed)
        # Skip header/menu containers
        cls = ' '.join(el.get('class', [])).lower()
        if any(kw in cls for kw in ['menu','widget','sidebar','share','social','footer','related','breadcrumb','pagination','tags','meta','author','byline','reaction','vote']):
            continue
        # Skip if any ancestor is in skip class
        skip = False
        for anc in el.parents:
            if anc is None or not hasattr(anc, 'get'):
                continue
            acls = ' '.join(anc.get('class', []) or []).lower()
            aid = (anc.get('id') or '').lower()
            if any(kw in acls for kw in ['menu','widget','sidebar','share','social','footer','related','breadcrumb','pagination','tags','meta','author','byline','popup','modal','reaction','vote','comment','search']):
                skip = True
                break
            if any(kw in aid for kw in ['menu','sidebar','footer','search','popup','comment']):
                skip = True
                break
        if skip:
            continue
        text = el.get_text(' ', strip=True)
        if text:
            paragraphs.append(text)

    return '\n\n'.join(paragraphs)


for f in sorted(os.listdir(base)):
    if not f.endswith('.mhtml'):
        continue
    path = os.path.join(base, f)
    with open(path, 'rb') as fh:
        head = fh.read(2000).decode('latin-1', errors='ignore')
    slug = None
    for key, sl in SLUGS.items():
        if key in head:
            slug = sl
            break
    if not slug:
        slug = f.split('.')[0][:30]

    print(f'-> {slug}')
    html = parse_mhtml(path)
    text = extract_article_text(html)

    # Save cyrillic
    with open(os.path.join(out_dir, slug + '_cyr.txt'), 'w', encoding='utf-8') as oh:
        oh.write(text)
    # Save translit
    trans = translit(text)
    with open(os.path.join(out_dir, slug + '_translit.txt'), 'w', encoding='utf-8') as oh:
        oh.write(trans)
    print(f'   cyr: {len(text)} chars, translit: {len(trans)} chars')
