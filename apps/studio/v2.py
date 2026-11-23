"""Context for the v2 layouts (templates/studio/designs/v2/): the ground, the emphasised words, the figure.

`render.design_context` calls `context` for the layouts in `designs.V2_LAYOUTS` and merges the result in.
"""
import random
import re
from pathlib import Path

from django.conf import settings
from django.utils.html import escape
from django.utils.safestring import mark_safe

from . import style
from . import vectors as topic_vectors

# How the old colour schemes map onto the v2 grounds (so posts keep the choice the AI or the user made).
SCHEME_GROUND = {
    'primary': 'brand', 'secondary': 'brand', 'accent': 'brand', 'gradient': 'brand',
    'deep': 'deep', 'dusk': 'deep', 'dark': 'ink', 'light': 'paper', 'soft': 'tint',
}
GROUNDS = ('ink', 'deep', 'paper', 'tint', 'brand')

MOCKS = (
    ('calendar', 'مواعيد موعد حجز حجوزات جدول calendar appointment booking schedule bcms'),
    ('phone', 'تطبيق جوال موبايل هاتف تطبيقات app mobile whatsapp واتساب'),
    ('list', 'مخزون منتج منتجات صيدلية متجر عملاء مبيعات فواتير inventory store pharmacy customers invoices pms ims'),
)


def ground(name, pal):
    """CSS colours for a ground: bg, text, muted text, highlight and the panel colours."""
    p = pal
    if name == 'paper':
        g = {'bg': p['paper'], 'fg': p['text_dark'], 'muted': p['muted_dark'], 'hi': p['brand_on_paper'],
             'line': 'rgba(20,22,28,.13)', 'panel': '#ffffff', 'on_panel': p['text_dark']}
    elif name == 'tint':
        g = {'bg': p['tint'], 'fg': p['text_dark'], 'muted': p['muted_dark'], 'hi': style.hsl(style._hls(p['brand'])[0], 0.7, 0.3),
             'line': 'rgba(20,22,28,.16)', 'panel': p['paper'], 'on_panel': p['text_dark']}
    elif name == 'brand':
        g = {'bg': p['brand'], 'fg': p['on_brand'], 'muted': f"color-mix(in srgb, {p['on_brand']} 78%, transparent)", 'hi': p['on_brand'],
             'line': f"color-mix(in srgb, {p['on_brand']} 30%, transparent)", 'panel': p['ink'], 'on_panel': '#ffffff'}
    elif name == 'deep':
        g = {'bg': f"linear-gradient(160deg, {p['deep']} 0%, {p['ink']} 100%)", 'fg': '#ffffff', 'muted': p['muted_light'], 'hi': p['brand_on_ink'],
             'line': 'rgba(255,255,255,.16)', 'panel': p['deep'], 'on_panel': '#ffffff'}
    else:  # ink
        g = {'bg': p['ink'], 'fg': '#ffffff', 'muted': p['muted_light'], 'hi': p['brand_on_ink'],
             'line': 'rgba(255,255,255,.16)', 'panel': p['deep'], 'on_panel': '#ffffff'}
    base = {'paper': p['paper'], 'tint': p['tint'], 'brand': p['brand']}.get(name, p['ink'])
    # Fills (tag, rule, marker) use the brand colour itself; text uses the accent only where it is readable.
    g['shape'] = g['hi'] if name == 'brand' else p['brand']
    if name in ('paper', 'tint') and style.contrast(p['brand'], base) < 3:
        g['hi'] = p['text_dark']
    g['on_shape'] = style.on(g['shape']) if name != 'brand' else p['brand']
    g['display'] = p['brand'] if name != 'brand' and style.contrast(p['brand'], base) >= 1.8 else g['hi']
    g['on_hi'] = g['on_shape']
    pill_bg = p['ink'] if style.contrast(p['brand'], p['ink']) >= 3 else p['paper']
    g['pill_bg'] = pill_bg
    g['pill_fg'] = p['brand'] if style.contrast(p['brand'], pill_bg) >= 3 else style.on(pill_bg)
    return g


def highlight(headline, seed):
    """The headline with one phrase wrapped in <span class="hl">, chosen by the seed (empty for very short ones)."""
    words = headline.split()
    if len(words) < 3:
        return mark_safe(escape(headline))
    rng = random.Random(seed)
    mode = rng.choice(('last', 'last', 'first', 'last2'))
    n = 2 if mode == 'last2' and len(words) >= 4 else 1
    if mode == 'first':
        a, b = words[:n], words[n:]
        parts = [f'<span class="hl">{escape(" ".join(a))}</span>', escape(' '.join(b))]
    else:
        a, b = words[:-n], words[-n:]
        parts = [escape(' '.join(a)), f'<span class="hl">{escape(" ".join(b))}</span>']
    return mark_safe(' '.join(parts))


FIGURE_RE = re.compile(r'^\s*([^\d\s]{0,2}\s?[\d][\d.,/:]*)\s*(.*?)\s*$')


def figure_parts(badge, headline=''):
    """(number, unit) for the hero figure: '99.9%' -> ('99.9', '%'), '9 سنوات' -> ('9', 'سنوات'), '24/7' -> ('24/7', '')."""
    for text in (badge, headline):
        m = FIGURE_RE.match(text or '') or re.search(r'(\d[\d.,/]*)\s*(%|٪)?', text or '')
        if not m:
            continue
        if m.re is FIGURE_RE:
            return m.group(1).strip(), m.group(2).strip()
        return m.group(1), (m.group(2) or '')
    return '', ''


def has_word(text, words):
    """Whether any of the `|`- or space-separated words occurs in the text: Latin ones as whole words, Arabic ones as
    substrings (so the prefixes ال و ب ل still match)."""
    text = text.lower()
    for w in re.split(r'[|\s]+', words):
        if not w:
            continue
        if w.isascii():
            if re.search(rf'(?<![a-z0-9]){re.escape(w)}(?![a-z0-9])', text):
                return True
        elif w in text:
            return True
    return False


def mock_kind(text, vectors):
    text = f'{text} {" ".join(vectors or [])}'
    for kind, words in MOCKS:
        if has_word(text, words):
            return kind
    return 'dashboard'


def split_points(subheadline):
    """List items from a subheadline written as lines or separated by | • ·, else an empty list."""
    parts = [p.strip(' -–—•·\t') for p in re.split(r'[\n|•·]+', subheadline or '') if p.strip(' -–—•·\t')]
    return parts if len(parts) >= 2 else []


def _mark_url(path, for_file):
    if for_file:
        return Path(path).as_uri()
    root = Path(settings.MEDIA_ROOT)
    try:
        return settings.MEDIA_URL + str(Path(path).relative_to(root))
    except ValueError:
        return ''


def seal_points(n=16, outer=98, inner=88):
    import math
    pts = []
    for i in range(n * 2):
        r = outer if i % 2 == 0 else inner
        a = math.pi * i / n
        pts.append(f'{100 + r * math.cos(a):.1f},{100 + r * math.sin(a):.1f}')
    return ' '.join(pts)


def context(company, fields, *, for_file, template, scheme, variant, logo_path):
    pal = style.palette(company.primary_color, company.secondary_color, company.accent_color)
    sh = style.shape(company)
    rng = random.Random(variant)
    name = SCHEME_GROUND.get(scheme, scheme)
    if name not in GROUNDS:
        name = 'ink'
    g = ground(name, pal)

    mark = mk = logo_img = ''
    if logo_path:
        try:
            path = style.logo_mark(logo_path)
            flat = style.is_flat(path) if path else True
        except Exception:  # a broken or unreadable logo file must not stop the design
            path, flat = '', True
        if path and not flat:
            # A multi-colour logo keeps its own colours: shown as it is on light grounds, on a chip elsewhere.
            logo_img = _mark_url(path, for_file) if name in ('paper', 'tint') else ''
        elif path:
            mark = _mark_url(path, for_file)
            own = style.mark_colour(path, pal['brand'])
            mk = own if style.contrast(own, pal['ink'] if name in ('ink', 'deep') else g['fg']) >= 2.6 and name != 'brand' else g['fg']
            if name in ('paper', 'tint') and style.contrast(own, pal['paper']) < 3:
                mk = pal['text_dark']
    if not mk:
        mk = g['fg']
    if sh['ornament'] == 'mark' and not mark:
        sh = {**sh, 'ornament': 'glow'}  # the giant logo watermark needs a keyed-out mark

    headline = fields['headline']
    figure, unit = figure_parts(fields.get('badge', ''), headline)
    text = ' '.join(str(fields.get(k, '')) for k in ('headline', 'subheadline', 'title', 'pillar'))
    chosen = fields.get('vectors') or []
    if isinstance(chosen, str):
        chosen = [x for x in chosen.split(',') if x]
    art = topic_vectors.for_post(chosen, fields['headline'], fields.get('subheadline', ''), fields.get('title', ''), fields.get('pillar', ''))[:3]
    look = {
        'x': rng.randint(10, 90), 'y': rng.randint(10, 90), 'rot': rng.choice((-35, 35, 45, 60, 120, 135)),
        'scale': round(rng.uniform(0.8, 1.3), 2), 'align': rng.choice(('center', 'end')),
        'badge_top': rng.random() < 0.4, 'mark': rng.random() < 0.3, 'emblem': rng.random() < 0.6,
    }
    emblem_on = bool(look['emblem'] and look['align'] == 'end' and len(art) >= 2 and len(headline.split()) <= 6 and fields.get('size') != 'story' and template == 'statement')
    return {
        'pal': pal, 'sh': sh, 'g': g, 'ground': name, 'mark': mark, 'mk': mk, 'logo_img': logo_img,
        'v': look, 'emblem_on': emblem_on,
        'headline_html': highlight(headline, variant),
        'fig_main': figure, 'fig_unit': unit, 'fig_ltr': (not unit) or unit in ('%', '٪', '+', 'k', 'K', 'M'),
        'mock': mock_kind(text, chosen),
        'points': split_points(fields.get('subheadline', '')),
        'seal_points': seal_points(),
        'art': art,
    }
