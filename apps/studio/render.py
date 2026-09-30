"""Render post designs: HTML templates -> PNG, through headless Chrome.

The same template is used twice: served as a page for the live preview in the
post editor (assets by URL), and written to a temp file that Chrome screenshots
for the final image (assets by file:// path, so rendering needs no web server).
"""
import re
import tempfile
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path

from django.conf import settings
from django.contrib.staticfiles import finders
from django.core.files.base import ContentFile
from django.template.loader import render_to_string
from django.templatetags.static import static

from .designs import FONT_FAMILIES, SIZES, TEMPLATES

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
    return {
        **fields,
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
