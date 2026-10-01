"""Read a company's website to pre-fill its brand kit.

The URL comes from the user and is fetched by our server, so every request
(including each redirect hop) is checked to resolve to a public address only:
no localhost, private networks or cloud metadata endpoints.
"""
import ipaddress
import re
import socket
from collections import Counter
from html.parser import HTMLParser
from urllib.parse import urljoin, urlparse

import requests
from django.utils.translation import gettext_lazy as _

USER_AGENT = 'Mozilla/5.0 (compatible; WakeelBot/1.0; +https://wakeel.app)'
MAX_BYTES = 2 * 1024 * 1024
MAX_TEXT = 24000
EXTRA_PAGE_HINTS = ('about', 'who-we-are', 'company', 'services', 'products', 'solutions',
                    'من-نحن', 'عن', 'خدمات', 'منتجات', 'حلول')


class FetchError(Exception):
    """A user-facing (Arabic) reason the site couldn't be read."""


def _check_public(url):
    parts = urlparse(url)
    if parts.scheme not in ('http', 'https') or not parts.hostname:
        raise FetchError(_('الرابط غير صالح. استخدم رابطاً يبدأ بـ http أو https.'))
    try:
        infos = socket.getaddrinfo(parts.hostname, parts.port or (443 if parts.scheme == 'https' else 80))
    except socket.gaierror as exc:
        raise FetchError(_('تعذّر العثور على هذا الموقع. تأكد من كتابة الرابط بشكل صحيح.')) from exc
    for info in infos:
        if not ipaddress.ip_address(info[4][0]).is_global:
            raise FetchError(_('لا يمكن قراءة هذا العنوان.'))


def safe_get(url, *, accept='text/html', max_bytes=MAX_BYTES):
    """GET a public URL, following up to 4 redirects; returns (final_url, content_type, bytes)."""
    for _attempt in range(5):
        _check_public(url)
        try:
            resp = requests.get(url, headers={'User-Agent': USER_AGENT, 'Accept': accept}, timeout=12,
                                stream=True, allow_redirects=False)
        except requests.RequestException as exc:
            raise FetchError(_('تعذّر الاتصال بالموقع. تأكد من أنه يعمل ثم حاول مرة أخرى.')) from exc
        if resp.is_redirect and resp.headers.get('Location'):
            url = urljoin(url, resp.headers['Location'])
            resp.close()
            continue
        if resp.status_code != 200:
            resp.close()
            raise FetchError(_('رد الموقع برمز %(code)s. تأكد من الرابط.') % {'code': resp.status_code})
        body = b''
        for chunk in resp.iter_content(64 * 1024):
            body += chunk
            if len(body) > max_bytes:
                break
        resp.close()
        return url, resp.headers.get('Content-Type', ''), body[:max_bytes]
    raise FetchError(_('الموقع يعيد التوجيه مرات كثيرة.'))


class _PageParser(HTMLParser):
    SKIP = {'script', 'style', 'noscript', 'svg', 'template'}

    def __init__(self):
        super().__init__(convert_charrefs=True)
        self.text, self.links, self.meta, self.logo_candidates = [], [], {}, []
        self.title = ''
        self._skip = 0
        self._in_title = False

    def handle_starttag(self, tag, attrs):
        a = {k: (v or '') for k, v in attrs}
        if tag in self.SKIP:
            self._skip += 1
        elif tag == 'title':
            self._in_title = True
        elif tag == 'meta':
            key = (a.get('property') or a.get('name') or '').lower()
            if key and a.get('content'):
                self.meta[key] = a['content'].strip()
        elif tag == 'a' and a.get('href'):
            self.links.append(a['href'].strip())
        elif tag == 'link' and 'icon' in a.get('rel', '').lower() and a.get('href'):
            size = max((int(n) for n in re.findall(r'(\d+)x\d+', a.get('sizes', ''))), default=0)
            self.logo_candidates.append((1 if 'apple' in a['rel'].lower() else 0, size, a['href']))
        elif tag == 'img':
            hint = ' '.join((a.get('src', ''), a.get('alt', ''), a.get('class', ''), a.get('id', ''))).lower()
            if 'logo' in hint and a.get('src'):
                self.logo_candidates.append((3, 0, a['src']))

    def handle_endtag(self, tag):
        if tag in self.SKIP and self._skip:
            self._skip -= 1
        elif tag == 'title':
            self._in_title = False

    def handle_data(self, data):
        if self._in_title:
            self.title += data
        elif not self._skip:
            text = ' '.join(data.split())
            if text:
                self.text.append(text)


def _parse(url, body):
    parser = _PageParser()
    parser.feed(body.decode('utf-8', errors='replace'))
    return parser


_HEX = re.compile(r'#([0-9a-fA-F]{6})\b')


def _brand_colors(html, css):
    """Most used saturated colours in the page's HTML and first stylesheet (greys ignored)."""
    counts = Counter()
    for match in _HEX.findall(html + css):
        r, g, b = (int(match[i:i + 2], 16) for i in (0, 2, 4))
        if max(r, g, b) - min(r, g, b) < 40:  # grey, white or black
            continue
        counts['#' + match.lower()] += 1
    return [color for color, _ in counts.most_common(3)]


def _socials(links):
    found = {}
    for href in links:
        low = href.lower()
        if 'facebook.com/' in low and 'sharer' not in low:
            found.setdefault('facebook_page', href)
        elif 'instagram.com/' in low:
            handle = urlparse(href).path.strip('/').split('/')[0]
            if handle and handle not in ('p', 'reel', 'explore'):
                found.setdefault('instagram_handle', handle)
        elif 'tiktok.com/@' in low:
            found.setdefault('tiktok_handle', urlparse(href).path.strip('/').split('/')[0].lstrip('@'))
        elif low.startswith('tel:'):
            found.setdefault('phone', href[4:].strip())
        elif 'wa.me/' in low or 'api.whatsapp.com' in low:
            number = re.sub(r'\D', '', urlparse(href).path) or re.sub(r'\D', '', href.split('phone=')[-1])[:15]
            if number:
                found.setdefault('whatsapp', '+' + number)
    return found


def read_site(url):
    """Fetch the home page and a few about/services pages. Returns what's needed to pre-fill a brand kit."""
    url = url.strip()
    if '://' not in url:
        url = 'https://' + url
    final_url, ctype, body = safe_get(url)
    if 'html' not in ctype.lower():
        raise FetchError(_('الرابط لا يشير إلى صفحة ويب.'))
    home = _parse(final_url, body)
    html = body.decode('utf-8', errors='replace')
    host = urlparse(final_url).hostname

    pages = [(_('الصفحة الرئيسية'), home.text)]
    seen = {final_url.rstrip('/')}
    for href in home.links:
        link = urljoin(final_url, href).split('#')[0].rstrip('/')
        if urlparse(link).hostname != host or link in seen:
            continue
        if any(hint in link.lower() or hint in href for hint in EXTRA_PAGE_HINTS):
            seen.add(link)
            try:
                _url, sub_type, sub_body = safe_get(link)
            except FetchError:
                continue
            if 'html' in sub_type.lower():
                pages.append((link, _parse(link, sub_body).text))
            if len(pages) >= 4:
                break

    # Fallback colours (the visual probe is the main source): the site's own stylesheets.
    css = ''
    for tag in re.findall(r'<link\b[^>]*>', html, re.I):
        href = re.search(r'href=["\']([^"\']+)', tag)
        if 'stylesheet' not in tag.lower() or not href:
            continue
        sheet = urljoin(final_url, href.group(1))
        if urlparse(sheet).hostname != host:
            continue
        try:
            css += safe_get(sheet, accept='text/css', max_bytes=512 * 1024)[2].decode('utf-8', 'replace')
        except FetchError:
            continue
        if len(css) > 400_000:
            break

    text, used = [], 0
    for name, chunks in pages:
        block = f'--- {name} ---\n' + '\n'.join(dict.fromkeys(chunks))
        text.append(block[:MAX_TEXT - used])
        used += len(text[-1])
        if used >= MAX_TEXT:
            break

    # Best logo candidate that isn't SVG (the logo field stores raster images only).
    candidates = [c[2] for c in sorted(home.logo_candidates, key=lambda c: (c[0], c[1]), reverse=True)]
    candidates.append(home.meta.get('og:image', ''))
    logo = next((urljoin(final_url, c) for c in candidates
                 if c and not urlparse(c).path.lower().endswith('.svg') and not c.startswith('data:')), '')

    colors = _brand_colors(html, css)
    if home.meta.get('theme-color', '').startswith('#') and len(home.meta['theme-color']) == 7:
        colors = [home.meta['theme-color'].lower()] + [c for c in colors if c != home.meta['theme-color'].lower()]

    return {
        'url': final_url,
        'title': home.title.strip() or home.meta.get('og:site_name', ''),
        'description': home.meta.get('description') or home.meta.get('og:description', ''),
        'text': '\n\n'.join(text),
        'logo_url': logo,
        'colors': colors[:3],
        'contacts': _socials(home.links),
    }
