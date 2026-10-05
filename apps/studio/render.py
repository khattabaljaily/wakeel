"""Render post designs: HTML templates -> PNG, through headless Chrome.

The same template is used twice: served as a page for the live preview in the
post editor (assets by URL), and written to a temp file that Chrome screenshots
for the final image (assets by file:// path, so rendering needs no web server).
"""
import random
import re
import tempfile
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path

from django.conf import settings
from django.contrib.staticfiles import finders
from django.core.files.base import ContentFile
from django.template.loader import render_to_string
from django.templatetags.static import static

from . import vectors as topic_vectors
from .designs import ART_TEMPLATES, DEFAULT_MOTIF, FONT_FAMILIES, MOTIFS, SCHEMES, SIZES, TEMPLATES

ARABIC_RE = re.compile(r'[\u0600-\u06FF]')


# --- colours ----------------------------------------------------------------

def _rgb(hex_color):
    h = hex_color.lstrip('#')
    return tuple(int(h[i:i + 2], 16) for i in (0, 2, 4))


def _hex(rgb):
    return '#' + ''.join(f'{max(0, min(255, round(c))):02x}' for c in rgb)


def _luminance(hex_color):
    def channel(c):
        c /= 255
        return c / 12.92 if c <= 0.03928 else ((c + 0.055) / 1.055) ** 2.4
    r, g, b = (channel(c) for c in _rgb(hex_color))
    return 0.2126 * r + 0.7152 * g + 0.0722 * b


def on_color(hex_color):
    """Readable text colour (white or near-black) on the given background."""
    return '#ffffff' if _luminance(hex_color) < 0.42 else '#111827'


def mix(hex_color, other, amount):
    a, b = _rgb(hex_color), _rgb(other)
    return _hex(tuple(x + (y - x) * amount for x, y in zip(a, b)))


def contrast(a, b):
    hi, lo = sorted((_luminance(a), _luminance(b)), reverse=True)
    return (hi + 0.05) / (lo + 0.05)


SOFTEN = 0.18  # share of white mixed into coloured grounds, at most


def soften(color):
    """The colour with up to SOFTEN of white mixed in, but only as much as keeps its text readable
    (contrast 4.5 with the same text colour): amber gets lighter, a mid blue stays close to itself."""
    text = on_color(color)
    for amount in (SOFTEN, SOFTEN * 2 / 3, SOFTEN / 3):
        lighter = mix(color, '#ffffff', amount)
        if on_color(lighter) == text and contrast(lighter, text) >= 4.5:
            return lighter
    return color


def palette(scheme, p, s, a):
    """The colours a design uses, for a colour scheme built from the brand's three colours.

    bg is a CSS background (a colour or a gradient), fg the text colour on it, ac the
    accent for buttons and shapes (the first brand colour that stands out from the
    background, else the text colour), soft a subtle panel colour on the background.
    """
    p_dark, p_deep, p_light = mix(p, '#000000', 0.45), mix(p, '#000000', 0.6), mix(p, '#ffffff', 0.85)
    ink = mix(p, '#000000', 0.78)
    # Coloured grounds are softened with a little white so a full-bleed brand colour isn't harsh;
    # buttons and shapes (ac) keep the brand's exact colours.
    tp, ts, ta = (soften(c) for c in (p, s, a))
    if scheme == 'secondary':
        base, order = ts, (a, p)
    elif scheme == 'accent':
        base, order = ta, (p, s)
    elif scheme == 'deep':
        base, order = p_deep, (a, s, p)
    elif scheme == 'light':
        base, order = '#f7f6f2', (p, s, a)
    elif scheme == 'soft':
        base, order = p_light, (p, s, a)
    elif scheme == 'gradient':
        base, order = mix(tp, ts, 0.5), (a, '#ffffff')
    elif scheme == 'dusk':
        base, order = mix(p_deep, tp, 0.5), (a, s, '#ffffff')
    elif scheme == 'dark':
        base, order = '#0f1115', (a, s, p)
    else:  # primary
        base, order = tp, (a, s)
    bg = {
        'gradient': f'linear-gradient(140deg, {tp} 0%, {tp} 25%, {ts} 100%)',
        'dusk': f'linear-gradient(160deg, {p_deep} 0%, {tp} 100%)',
    }.get(scheme, base)
    fg = on_color(base)
    if scheme in ('light', 'soft'):
        fg = ink
    ac = next((c for c in order if contrast(base, c) >= 2.2), fg)
    return {
        'bg': bg, 'bg_base': base, 'fg': fg, 'ac': ac, 'on_ac': on_color(ac),
        'soft': mix(base, fg, 0.10), 'line': mix(base, fg, 0.28),
        'muted': mix(base, fg, 0.30 if fg == '#ffffff' else 0.38) if scheme in ('light', 'soft') else fg,
    }


def variation(seed):
    """Small deterministic differences between posts that share a layout, scheme and motif."""
    r = random.Random(seed)
    return {
        'x': r.randint(8, 92), 'y': r.randint(8, 92), 'rot': r.choice((-35, -20, 15, 30, 45, 60, 120, 135)),
        'scale': round(r.uniform(0.8, 1.35), 2), 'flip': r.choice((1, -1)),
        'cta': r.choice(('pill', 'pill', 'square', 'outline', 'underline')),
        'badge': r.choice(('pill', 'tag', 'sticker', 'plain')),
    }


# --- context ----------------------------------------------------------------

def post_fields(post, overrides=None):
    fields = {
        'headline': post.headline,
        'subheadline': post.subheadline,
        'cta': post.cta,
        'badge': post.badge,
        'template': post.template,
        'size': post.size,
        'background': post.background,
        'motif': post.motif,
        'scheme': post.scheme,
        'variant': post.variant or post.pk or 0,
        'vectors': post.vectors,
        'title': post.title,
        'pillar': post.pillar,
    }
    fields.update(overrides or {})
    if fields['template'] not in TEMPLATES:
        fields['template'] = 'bold'
    if fields['size'] not in SIZES:
        fields['size'] = 'square'
    return fields


def design_context(company, fields, *, for_file=False):
    width, height = SIZES[fields['size']]
    background = fields.get('background')
    if for_file:
        font_css = Path(finders.find('fonts/fonts.css')).as_uri()
        logo = Path(company.logo.path).as_uri() if company.logo else ''
        photo = Path(background.file.path).as_uri() if background else ''
    else:
        font_css = static('fonts/fonts.css')
        logo = company.logo.url if company.logo else ''
        photo = background.file.url if background else ''

    text = f"{fields['headline']} {fields['subheadline']}"
    contact = [c for c in (
        company.website.replace('https://', '').replace('http://', '').rstrip('/'),
        f'@{company.instagram_handle.lstrip("@")}' if company.instagram_handle else '',
        company.phone,
    ) if c][:2]
    p, s, a = company.primary_color, company.secondary_color, company.accent_color
    template = fields['template']
    scheme = fields.get('scheme') if fields.get('scheme') in SCHEMES else TEMPLATES[template]['scheme']
    motif = fields.get('motif') if fields.get('motif') in MOTIFS else DEFAULT_MOTIF.get(template, 'none')
    try:
        variant = int(fields.get('variant') or 0)
    except (TypeError, ValueError):
        variant = 0
    first, _, rest = fields['headline'].strip().partition(' ')
    chosen = fields.get('vectors') or []
    if isinstance(chosen, str):  # from the editor's preview: "key,key"
        chosen = [v for v in chosen.split(',') if v]
    art = topic_vectors.for_post(chosen, fields['headline'], fields['subheadline'], fields.get('title', ''),
                                 fields.get('pillar', '')) if template in ART_TEMPLATES else []
    return {
        'art': art,
        **fields,
        'scheme': scheme,
        'motif': motif,
        'v': variation(variant),
        'k': palette(scheme, p, s, a),
        'headline_first': first,
        'headline_rest': rest,
        'company': company,
        'width': width,
        'height': height,
        'dir': 'rtl' if ARABIC_RE.search(text) or not text.strip() else 'ltr',
        'font_css': font_css,
        'logo': logo,
        'photo': photo,
        'contact': contact,
        'heading_font': FONT_FAMILIES.get(company.heading_font, 'Cairo'),
        'body_font': FONT_FAMILIES.get(company.body_font, 'Tajawal'),
        'c': {
            'p': p, 's': s, 'a': a,
            'on_p': on_color(p), 'on_s': on_color(s), 'on_a': on_color(a),
            'p_dark': mix(p, '#000000', 0.45), 'p_deep': mix(p, '#000000', 0.7),
            'p_light': mix(p, '#ffffff', 0.85), 'ink': mix(p, '#000000', 0.78),
        },
    }


def render_html(company, fields, *, for_file=False):
    context = design_context(company, fields, for_file=for_file)
    return render_to_string(f'studio/designs/{fields["template"]}.html', context)


# --- rendering --------------------------------------------------------------

class Renderer:
    """One headless Chrome, reused for a batch of screenshots.

    Playwright's sync API runs an event loop in the thread that starts it, and
    Django refuses ORM calls from a thread with a running loop. So the browser
    lives on its own thread and callers stay free to touch the database.
    """

    def __enter__(self):
        self._pool = ThreadPoolExecutor(max_workers=1, thread_name_prefix='wakeel-render')
        self._pool.submit(self._start).result()
        return self

    def __exit__(self, *exc):
        self._pool.submit(self._stop).result()
        self._pool.shutdown()

    def _start(self):
        from playwright.sync_api import sync_playwright

        self._pw = sync_playwright().start()
        self._browser = self._pw.chromium.launch(
            executable_path=settings.CHROME_PATH or None,
            args=['--no-sandbox', '--allow-file-access-from-files', '--font-render-hinting=none'],
        )
        self._tmp = tempfile.TemporaryDirectory(prefix='wakeel-render-')

    def _stop(self):
        self._browser.close()
        self._pw.stop()
        self._tmp.cleanup()

    def png(self, html, width, height):
        return self._pool.submit(self._png, html, width, height).result()

    def _png(self, html, width, height):
        path = Path(self._tmp.name) / 'design.html'
        path.write_text(html, encoding='utf-8')
        page = self._browser.new_page(viewport={'width': width, 'height': height}, device_scale_factor=1)
        try:
            page.goto(path.as_uri())
            page.wait_for_function('window.__ready === true', timeout=20000)
            return page.screenshot(type='png', clip={'x': 0, 'y': 0, 'width': width, 'height': height})
        finally:
            page.close()


def render_posts(posts, progress=None):
    if not posts:
        return
    with Renderer() as renderer:
        for done, post in enumerate(posts, 1):
            fields = post_fields(post)
            data = renderer.png(render_html(post.company, fields, for_file=True), *SIZES[fields['size']])
            old = post.image.name if post.image else ''
            post.image.save(f'post-{post.pk}.png', ContentFile(data), save=False)
            post.image_stale = False
            post.save(update_fields=['image', 'image_stale'])
            if old and old != post.image.name:
                post.image.storage.delete(old)
            if progress:
                progress(done, len(posts))
