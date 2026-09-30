"""Look at a website the way a visitor sees it: find its logo and brand colours.

Headless Chrome renders the page (so CSS files, CSS variables and JS-built
sites all count), picks the logo element in the header and screenshots it
(works for SVG and CSS-background logos too), and weighs the colours actually
painted on buttons, links, headings and large areas. The logo's own colours
count most, since they are usually the brand colours.

Every request the page makes goes through the same public-address check as
scrape.safe_get, so a page can't make our server load internal URLs.
"""
import io
import logging
from concurrent.futures import ThreadPoolExecutor
from urllib.parse import urlparse

from django.conf import settings
from PIL import Image

from .scrape import FetchError, _check_public, safe_get

logger = logging.getLogger(__name__)

PROBE_JS = r"""
() => {
  const visible = el => {
    const r = el.getBoundingClientRect(), s = getComputedStyle(el);
    return r.width > 0 && r.height > 0 && s.visibility !== 'hidden' && s.display !== 'none' && +s.opacity > 0.1;
  };
  const cls = el => (typeof el.className === 'string' ? el.className : (el.className && el.className.baseVal) || '');

  // Logo: an image/svg (or an element named "logo") near the top, preferably inside the header and linking home.
  let best = null, bestScore = 2;
  document.querySelectorAll('img, svg, [class*="logo" i], [id*="logo" i]').forEach(el => {
    if (el.tagName.toLowerCase() !== 'svg' && el.closest('svg')) return;
    if (!visible(el)) return;
    const r = el.getBoundingClientRect();
    if (r.top > 450 || r.width < 24 || r.height < 14 || r.width > 700 || r.height > 320) return;
    const isGraphic = el.tagName === 'IMG' || el.tagName.toLowerCase() === 'svg' || getComputedStyle(el).backgroundImage !== 'none';
    if (!isGraphic) return;
    const link = el.closest('a');
    const href = link ? (link.getAttribute('href') || '') : '';
    const hint = [cls(el), el.id, el.getAttribute('alt'), el.getAttribute('src'), link && cls(link)].join(' ').toLowerCase();
    let score = 0;
    if (hint.includes('logo') || hint.includes('brand')) score += 4;
    if (el.closest('header, nav, [class*="header" i], [class*="navbar" i], [class*="topbar" i]')) score += 3;
    if (link && ['/', './', location.origin, location.origin + '/', location.href].includes(href)) score += 3;
    if (link && new URL(link.href, location.href).pathname.replace(/\/(ar|en)\/?$/, '/') === '/') score += 1;
    score -= r.top / 250;
    if (score > bestScore) { bestScore = score; best = el; }
  });
  if (best) best.setAttribute('data-wakeel-logo', '1');

  // Colours, weighted by how prominent they are.
  const weights = {};
  const add = (value, weight) => {
    const m = value && value.match(/rgba?\((\d+),\s*(\d+),\s*(\d+)(?:,\s*([\d.]+))?/);
    if (!m || (m[4] !== undefined && +m[4] < 0.6)) return;
    if (['0,0,238', '85,26,139', '0,0,255'].includes([m[1], m[2], m[3]].join(','))) return;  // browser default link colours
    const hex = '#' + [m[1], m[2], m[3]].map(x => (+x).toString(16).padStart(2, '0')).join('');
    weights[hex] = (weights[hex] || 0) + weight;
  };
  const vw = innerWidth;
  let n = 0;
  for (const el of document.querySelectorAll('body *')) {
    if (++n > 4000) break;
    if (!visible(el)) continue;
    const r = el.getBoundingClientRect(), s = getComputedStyle(el), tag = el.tagName;
    if (r.top > 3000) continue;
    add(s.backgroundColor, Math.min(r.width * r.height, vw * 400) / 2000);
    const buttonish = tag === 'BUTTON' || /\b(btn|button|cta)\b/i.test(cls(el)) || el.getAttribute('role') === 'button';
    if (buttonish) add(s.backgroundColor, 120);
    if (tag === 'A' || buttonish) add(s.color, 25);
    if (/^H[1-3]$/.test(tag)) add(s.color, 20);
    if (s.borderTopWidth !== '0px') add(s.borderTopColor, 5);
  }
  const theme = document.querySelector('meta[name="theme-color"]');
  if (theme) add(theme.content.startsWith('#') ? hexToRgb(theme.content) : theme.content, 150);
  function hexToRgb(h) { h = h.replace('#', ''); if (h.length === 3) h = h.split('').map(c => c + c).join(''); return `rgb(${parseInt(h.slice(0,2),16)}, ${parseInt(h.slice(2,4),16)}, ${parseInt(h.slice(4,6),16)})`; }
  return { colors: weights, logo: !!best, logoSrc: best && best.tagName === 'IMG' ? (best.currentSrc || best.src) : '' };
}
"""


def _rgb(hex_color):
    h = hex_color.lstrip('#')
    return tuple(int(h[i:i + 2], 16) for i in (0, 2, 4))


def _is_neutral(rgb):
    return max(rgb) - min(rgb) < 36 or max(rgb) < 30 or min(rgb) > 235


def _distance(a, b):
    return sum((x - y) ** 2 for x, y in zip(a, b)) ** 0.5


def _logo_colors(png):
    """Dominant non-neutral colours of the logo image, with their pixel share."""
    with Image.open(io.BytesIO(png)) as im:
        im = im.convert('RGBA')
        im.thumbnail((96, 96))
        counts = {}
        for r, g, b, a in im.getdata():
            if a < 200 or _is_neutral((r, g, b)):
                continue
            key = (r // 12 * 12, g // 12 * 12, b // 12 * 12)
            counts[key] = counts.get(key, 0) + 1
    total = sum(counts.values()) or 1
    return {'#%02x%02x%02x' % key: count / total for key, count in counts.items() if count / total >= 0.04}


def pick_palette(page_weights, logo_share=None, limit=3):
    """Merge similar colours, drop neutrals, and return up to `limit` hex colours, most important first."""
    scores = {}
    for hex_color, weight in page_weights.items():
        scores[hex_color] = scores.get(hex_color, 0) + weight
    # The logo decides the brand colours whenever it has any.
    page_total = sum(scores.values()) or 1
    for hex_color, share in (logo_share or {}).items():
        scores[hex_color] = scores.get(hex_color, 0) + share * page_total * 1.5

    clusters = []  # [rgb, score]
    for hex_color, score in sorted(scores.items(), key=lambda kv: -kv[1]):
        rgb = _rgb(hex_color)
        if _is_neutral(rgb):
            continue
        for cluster in clusters:
            if _distance(cluster[0], rgb) < 48:
                cluster[1] += score
                break
        else:
            clusters.append([rgb, score])
    clusters.sort(key=lambda c: -c[1])
    # Drop incidental colours (an icon, a screenshot inside the page) that barely register next to the main one.
    palette = ['#%02x%02x%02x' % tuple(c[0]) for c in clusters[:limit] if c[1] >= 0.02 * page_total]

    # Dark sites: a near-black background that dominates the page is part of the brand too.
    darks = [(score, hex_color) for hex_color, score in page_weights.items()
             if max(_rgb(hex_color)) < 70 and max(_rgb(hex_color)) - min(_rgb(hex_color)) < 36]
    page_sum = sum(page_weights.values()) or 1
    if darks:
        score, dark = max(darks)
        if score >= 0.2 * page_sum and dark not in palette:
            palette.insert(1 if palette else 0, dark)
    return palette[:limit]


def _to_png(data):
    with Image.open(io.BytesIO(data)) as im:
        im.load()
        out = io.BytesIO()
        im.convert('RGBA').save(out, 'PNG')
        return out.getvalue()


def _original_logo(browser, guard, src):
    """The logo file itself (sharper, and transparent). SVGs are rasterised by Chrome."""
    try:
        if urlparse(src).path.lower().endswith('.svg'):
            page = browser.new_page(viewport={'width': 800, 'height': 400}, device_scale_factor=3)
            page.route('**/*', guard)
            page.goto(src, timeout=10000)
            png = page.locator('svg').first.screenshot(omit_background=True, timeout=5000)
            page.close()
            return png
        _, _, data = safe_get(src, accept='image/*', max_bytes=2 * 1024 * 1024)
        return _to_png(data)
    except Exception:
        logger.info('Could not fetch original logo %s', src)
        return None


def _probe(url):
    from playwright.sync_api import sync_playwright

    allowed_hosts = {}

    def guard(route):
        request_url = route.request.url
        parts = urlparse(request_url)
        if parts.scheme == 'data':
            return route.continue_()
        if parts.scheme not in ('http', 'https') or route.request.resource_type in ('media', 'websocket'):
            return route.abort()
        host = parts.hostname
        if host not in allowed_hosts:
            try:
                _check_public(request_url)
                allowed_hosts[host] = True
            except FetchError:
                allowed_hosts[host] = False
        return route.continue_() if allowed_hosts[host] else route.abort()

    with sync_playwright() as pw:
        browser = pw.chromium.launch(executable_path=settings.CHROME_PATH or None, args=['--no-sandbox'])
        try:
            page = browser.new_page(viewport={'width': 1366, 'height': 900}, device_scale_factor=3)
            page.route('**/*', guard)
            page.goto(url, wait_until='domcontentloaded', timeout=25000)
            try:
                page.wait_for_load_state('networkidle', timeout=6000)
            except Exception:
                pass
            result = page.evaluate(PROBE_JS)
            logo = None
            src = result.get('logoSrc') or ''
            if src and not src.startswith('data:'):
                logo = _original_logo(browser, guard, src)
            if logo is None and result['logo']:
                try:
                    logo = page.locator('[data-wakeel-logo]').first.screenshot(omit_background=True, timeout=5000)
                except Exception:
                    logger.info('Logo screenshot failed for %s', url)
            return result['colors'], logo
        finally:
            browser.close()


def look_at(url):
    """Returns {'colors': [...], 'logo_png': bytes|None}. Never raises: a failure means 'nothing found'."""
    try:
        with ThreadPoolExecutor(max_workers=1) as pool:  # Playwright's loop must stay off the request thread
            page_colors, logo = pool.submit(_probe, url).result(timeout=60)
    except Exception:
        logger.exception('Visual probe failed for %s', url)
        return {'colors': [], 'logo_png': None}
    logo_share = {}
    if logo:
        try:
            logo_share = _logo_colors(logo)
        except OSError:
            logo = None
    return {'colors': pick_palette(page_colors, logo_share), 'logo_png': logo}
