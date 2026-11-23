"""The look of a brand in the v2 designs: its palette, its shape language and its logo as a one-colour mark.

Two companies with the same layout should still not look alike. So everything a layout draws with comes
from here and is derived from the company itself:

- `palette`: ink, paper and tints built on the brand's hue (never a muddy darkened primary);
- `shape`: corner radius, shadow, rule and ornament family, picked from the brand so it stays stable;
- `logo_mark`: the logo with its flat background removed, so it can be tinted to suit any ground
  (a white chip behind the logo is what made the old designs look like templates).
"""
import colorsys
import hashlib
import io
import os
import tempfile
from pathlib import Path

from django.conf import settings


# --- colour -----------------------------------------------------------------

def _rgb(hex_color):
    h = hex_color.lstrip('#')
    return tuple(int(h[i:i + 2], 16) / 255 for i in (0, 2, 4))


def _hex(r, g, b):
    return '#' + ''.join(f'{max(0, min(255, round(c * 255))):02x}' for c in (r, g, b))


def _hls(hex_color):
    return colorsys.rgb_to_hls(*_rgb(hex_color))


def hsl(h, s, l):
    return _hex(*colorsys.hls_to_rgb(h % 1, max(0, min(1, l)), max(0, min(1, s))))


def luminance(hex_color):
    def channel(c):
        return c / 12.92 if c <= 0.03928 else ((c + 0.055) / 1.055) ** 2.4
    r, g, b = (channel(c) for c in _rgb(hex_color))
    return 0.2126 * r + 0.7152 * g + 0.0722 * b


def contrast(a, b):
    hi, lo = sorted((luminance(a), luminance(b)), reverse=True)
    return (hi + 0.05) / (lo + 0.05)


def on(color, dark='#0e1116', light='#ffffff'):
    """The readable text colour on `color`."""
    return light if contrast(color, light) >= contrast(color, dark) else dark


def palette(primary, secondary, accent):
    """Ink, paper, tints and a vivid brand colour, all built on the brand's own hue.

    The dark ground is a near-black tinted with the brand hue, not the primary darkened: darkening an
    amber or a yellow gives brown mud, while a tinted black makes the brand colour glow on it.
    """
    h, l, s = _hls(primary)
    vivid = primary if 0.28 <= l <= 0.72 else hsl(h, max(s, 0.55), 0.5)
    sh, sl, ss = _hls(secondary)
    ink = hsl(h, min(s, 0.07), 0.07)
    deep = hsl(h, min(s, 0.10), 0.135)
    paper = hsl(h, min(s, 0.45), 0.965)
    tint = hsl(h, min(s, 0.75), 0.90)
    mid = hsl(h, min(s, 0.55), 0.78)
    second = secondary if contrast(secondary, ink) >= 2.5 or contrast(secondary, paper) >= 2.5 else vivid
    return {
        'brand': vivid, 'on_brand': on(vivid), 'brand2': second, 'on_brand2': on(second), 'accent': accent,
        'ink': ink, 'deep': deep, 'paper': paper, 'tint': tint, 'mid': mid,
        'text_dark': hsl(h, min(s, 0.18), 0.10), 'muted_dark': hsl(h, min(s, 0.10), 0.38),
        'muted_light': hsl(h, min(s, 0.12), 0.76),
        'brand_on_paper': vivid if contrast(vivid, paper) >= 3 else hsl(h, max(s, 0.6), 0.34),
        'brand_on_ink': vivid if contrast(vivid, ink) >= 4.5 else hsl(h, max(s, 0.6), 0.66),
    }


# --- shape language ---------------------------------------------------------

RADII = (0, 10, 22, 36, 56)
ORNAMENTS = ('glow', 'glow', 'mark', 'grid', 'arc', 'lattice')
RULES = ('bar', 'thin', 'dot', 'none')


def shape(company):
    """A stable, brand-specific set of shape choices: the same company always gets the same ones."""
    seed = hashlib.sha256(f'{company.name}|{company.primary_color}|{company.secondary_color}'.encode()).digest()
    return {
        'radius': RADII[seed[0] % len(RADII)],
        'ornament': ORNAMENTS[seed[1] % len(ORNAMENTS)],
        'rule': RULES[seed[2] % len(RULES)],
        'bar': seed[3] % 2 == 0,  # contact details on a solid band at the bottom instead of a thin rule
        'outline': seed[4] % 3 == 0,
        'weight': (700, 800, 800)[seed[5] % 3],
        'tracking': (0, 0, 0)[seed[6] % 3],
    }


# --- logo as a mark ---------------------------------------------------------

def _key_out_background(image):
    """A flat-background logo as RGBA whose alpha is the distance from that background colour.

    Returns None when the corners aren't one flat colour (a photo-like logo is used as it is).
    """
    from PIL import Image, ImageChops

    image = image.convert('RGBA')
    w, h = image.size
    corners = [image.getpixel(p)[:3] for p in ((0, 0), (w - 1, 0), (0, h - 1), (w - 1, h - 1))]
    bg = tuple(sum(c[i] for c in corners) // 4 for i in range(3))
    if max(abs(c[i] - bg[i]) for c in corners for i in range(3)) > 18:
        return None
    r, g, b, a = image.split()
    diff = ImageChops.difference(Image.merge('RGB', (r, g, b)), Image.new('RGB', image.size, bg)).split()
    far = ImageChops.lighter(ImageChops.lighter(diff[0], diff[1]), diff[2])
    alpha = ImageChops.multiply(far.point(lambda v: min(255, round(v * 2.2))), a)
    out = image.copy()
    out.putalpha(alpha)
    return out


def logo_mark(logo_path):
    """Path of a transparent version of the logo (made once and cached), or '' when it can't be one.

    A logo that already has transparency is used as it is. A logo on a flat background gets the background
    keyed out. Anything else returns '' and the designs fall back to showing the logo on a small chip.
    """
    from PIL import Image

    source = Path(logo_path)
    cache = Path(settings.MEDIA_ROOT or tempfile.gettempdir()) / 'studio-cache'
    cache.mkdir(parents=True, exist_ok=True)
    key = hashlib.sha1(f'{source}|{source.stat().st_mtime_ns}'.encode()).hexdigest()[:16]
    target = cache / f'mark-{key}.png'
    if target.exists():
        return str(target) if target.stat().st_size else ''
    image = Image.open(source)
    if image.mode in ('RGBA', 'LA') and image.getchannel('A').getextrema()[0] < 250:
        mark = image.convert('RGBA')
    else:
        mark = _key_out_background(image)
    data = b''
    if mark is not None:
        box = mark.getchannel('A').point(lambda v: 255 if v > 24 else 0).getbbox()
        if box:
            mark = mark.crop(box)
        buffer = io.BytesIO()
        mark.save(buffer, 'PNG')
        data = buffer.getvalue()
    # Written to a temporary name and moved into place, so a render running at the same time never reads half a file.
    fd, tmp = tempfile.mkstemp(dir=cache, suffix='.tmp')
    with os.fdopen(fd, 'wb') as handle:
        handle.write(data)
    os.replace(tmp, target)
    return str(target) if data else ''


def is_flat(mark_path):
    """Whether the mark is (nearly) one colour, so tinting it keeps the logo's identity."""
    from PIL import Image

    image = Image.open(mark_path).convert('RGBA').resize((64, 64))
    px = [p[:3] for p in image.getdata() if p[3] > 200]
    if not px:
        return True
    mean = [sum(p[i] for p in px) / len(px) for i in range(3)]
    close = sum(1 for p in px if max(abs(p[i] - mean[i]) for i in range(3)) < 48)
    return close / len(px) >= 0.8


def mark_colour(mark_path, fallback):
    """The dominant opaque colour of a keyed logo, so the mark can keep its own colour on a dark ground."""
    from PIL import Image

    image = Image.open(mark_path).convert('RGBA').resize((48, 48))
    px = [p for p in image.getdata() if p[3] > 200]
    if not px:
        return fallback
    n = len(px)
    return _hex(*(sum(p[i] for p in px) / n / 255 for i in range(3)))
