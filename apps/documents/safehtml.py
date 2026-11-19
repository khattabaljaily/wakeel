"""Designed documents: Claude writes the page as HTML and CSS (the way it designs when asked in a chat), and this module
makes it safe before it is stored or shown. Only a short list of tags, attributes and CSS properties survives; nothing
that loads anything (no scripts, links, images, fonts, @import, url()), nothing that escapes the page area. Every CSS
rule is scoped under `.dh`, so a design cannot restyle the app around it.

The output is an HTML fragment meant to be placed inside `<div class="dh">...</div>`."""
import re
from html import escape
from html.parser import HTMLParser

TAGS = {'div', 'span', 'p', 'h1', 'h2', 'h3', 'h4', 'h5', 'h6', 'table', 'thead', 'tbody', 'tfoot', 'tr', 'th', 'td', 'ul', 'ol',
        'li', 'strong', 'b', 'em', 'i', 'u', 's', 'br', 'hr', 'small', 'sub', 'sup', 'section', 'header', 'footer', 'article',
        'aside', 'main', 'colgroup', 'col', 'caption', 'dl', 'dt', 'dd', 'blockquote', 'label', 'abbr', 'mark', 'figure', 'figcaption'}
VOID = {'br', 'hr', 'col'}
SKIP_CONTENT = {'script', 'style', 'iframe', 'object', 'embed', 'svg', 'math', 'noscript', 'template', 'textarea', 'title', 'head'}
SIMPLE_ATTRS = {'colspan': re.compile(r'^\d{1,2}$'), 'rowspan': re.compile(r'^\d{1,2}$'), 'dir': re.compile(r'^(ltr|rtl|auto)$'),
                'lang': re.compile(r'^[A-Za-z-]{2,10}$'), 'class': re.compile(r'^[\w\- ]{1,120}$')}
PROPERTIES = {
    'color', 'background', 'background-color', 'background-image', 'border', 'border-top', 'border-bottom', 'border-left', 'border-right',
    'border-inline-start', 'border-inline-end', 'border-width', 'border-style', 'border-color', 'border-radius', 'border-collapse',
    'border-spacing', 'box-shadow', 'margin', 'margin-top', 'margin-bottom', 'margin-left', 'margin-right', 'margin-inline-start',
    'margin-inline-end', 'padding', 'padding-top', 'padding-bottom', 'padding-left', 'padding-right', 'padding-inline-start',
    'padding-inline-end', 'width', 'min-width', 'max-width', 'height', 'min-height', 'max-height', 'display', 'flex', 'flex-direction',
    'flex-wrap', 'flex-grow', 'flex-shrink', 'flex-basis', 'gap', 'row-gap', 'column-gap', 'grid-template-columns', 'grid-template-rows',
    'grid-column', 'grid-row', 'grid-gap', 'justify-content', 'align-items', 'align-self', 'justify-self', 'text-align', 'vertical-align',
    'font-size', 'font-weight', 'font-style', 'line-height', 'letter-spacing', 'word-spacing', 'text-decoration', 'text-transform',
    'white-space', 'direction', 'unicode-bidi', 'table-layout', 'page-break-inside', 'break-inside', 'page-break-after',
    'break-after', 'page-break-before', 'break-before', 'opacity', 'list-style', 'list-style-type', 'overflow', 'text-indent',
    'outline', 'float', 'clear', 'box-sizing', 'font-family', 'text-wrap', 'overflow-wrap', 'word-break',
}
BAD_VALUE = re.compile(r'url\s*\(|expression|javascript|@import|behavior|-moz-binding|\\|<|>|\{|\}|/\*|image-set|attr\s*\(|var\s*\(', re.I)
DISPLAY_OK = re.compile(r'^(block|inline|inline-block|flex|inline-flex|grid|inline-grid|table|table-row|table-cell|table-header-group|table-footer-group|none|list-item)$')
SELECTOR_OK = re.compile(r'^[\w\s.#>+~*:\-(),]+$')
PSEUDO_OK = re.compile(r':(?!first-child\b|last-child\b|nth-child\(|nth-of-type\(|first-of-type\b|last-of-type\b|not\(|empty\b|before\b|after\b|only-child\b)')
FONTS = ('"Almohanad"', "'Almohanad'", 'Almohanad', '"Noto Sans Arabic"', "'Noto Sans Arabic'", 'Noto Sans Arabic', '"Noto Sans"',
         'sans-serif', 'serif', 'monospace', 'Arial', 'Tahoma', 'system-ui')


def clean_declarations(text: str) -> str:
    """`color: red; background: url(x)` -> `color:red`: only listed properties, no value that loads or escapes."""
    out = []
    for part in (text or '').split(';'):
        if ':' not in part:
            continue
        name, value = part.split(':', 1)
        name, value = name.strip().lower(), re.sub(r'\s+', ' ', value.strip().replace('!important', '')).strip()
        if name not in PROPERTIES or not value or len(value) > 200 or BAD_VALUE.search(value):
            continue
        if name == 'display' and not DISPLAY_OK.match(value.lower()):
            continue
        if name == 'background-image' and not re.match(r'^(linear|radial)-gradient\(', value.lower()):
            continue
        if name == 'font-family':
            names = [n.strip() for n in value.split(',')]
            value = ', '.join(n for n in names if n in FONTS) or 'Almohanad, sans-serif'
        if name == 'overflow' and value not in ('hidden', 'visible', 'auto'):
            continue
        out.append(f'{name}:{value}')
    return ';'.join(out)


def clean_css(css: str) -> str:
    """The rules of a <style>, scoped under .dh; at-rules and anything unusual are dropped."""
    css = re.sub(r'/\*.*?\*/', '', css or '', flags=re.S)
    css = re.sub(r'@[a-zA-Z-]+[^{;]*\{(?:[^{}]*\{[^{}]*\})*[^{}]*\}', '', css)          # @media, @font-face, @keyframes...
    css = re.sub(r'@[a-zA-Z-]+[^;{]*;', '', css)                                          # @import, @charset
    rules = []
    for selectors, body in re.findall(r'([^{}]+)\{([^{}]*)\}', css):
        declarations = clean_declarations(body)
        if not declarations:
            continue
        scoped = []
        for selector in selectors.split(','):
            selector = selector.strip()
            if not selector or not SELECTOR_OK.match(selector) or PSEUDO_OK.search(selector) or len(selector) > 120:
                continue
            selector = re.sub(r'^(html|body)\b\s*', '', selector).strip()
            if selector == '.dh' or selector.startswith('.dh '):
                scoped.append(selector)                     # already scoped (the page was made safe before): stays as it is
            else:
                scoped.append('.dh ' + selector if selector else '.dh')
        if scoped:
            rules.append(f'{", ".join(scoped)}{{{declarations}}}')
    return '\n'.join(rules)


class _Cleaner(HTMLParser):
    def __init__(self):
        super().__init__(convert_charrefs=True)
        self.out, self.css, self.skip, self.in_style = [], [], 0, False

    def handle_starttag(self, tag, attrs):
        if tag in SKIP_CONTENT:
            if tag == 'style':
                self.in_style = True
            if tag not in ('textarea', 'title', 'head'):
                self.skip += 1
            return
        if self.skip or tag not in TAGS:
            return
        kept = []
        for name, value in attrs:
            value = value or ''
            if name == 'style':
                value = clean_declarations(value)
                if value:
                    kept.append(f'style="{escape(value, quote=True)}"')
            elif name in SIMPLE_ATTRS and SIMPLE_ATTRS[name].match(value):
                kept.append(f'{name}="{escape(value, quote=True)}"')
        self.out.append(f'<{tag}{" " + " ".join(kept) if kept else ""}>')

    def handle_endtag(self, tag):
        if tag in SKIP_CONTENT:
            if tag == 'style':
                self.in_style = False
            if self.skip and tag not in ('textarea', 'title', 'head'):
                self.skip -= 1
            return
        if not self.skip and tag in TAGS and tag not in VOID:
            self.out.append(f'</{tag}>')

    def handle_data(self, data):
        if self.in_style:
            self.css.append(data)
        elif not self.skip:
            self.out.append(escape(data, quote=False))


def clean_html(source: str) -> str:
    """The safe fragment (with its scoped <style> first), or '' when nothing is left."""
    source = re.sub(r'^\s*```(?:html)?\s*|\s*```\s*$', '', source or '')
    parser = _Cleaner()
    parser.feed(source)
    parser.close()
    body = ''.join(parser.out).strip()
    css = clean_css('\n'.join(parser.css))
    if not body:
        return ''
    return (f'<style>{css}</style>' if css else '') + body


BLANK = re.compile(r'\{\{\s*([^{}\n]{1,60}?)\s*\}\}')
EMPTY = '..........'
CHECKED = {'☑', '☒', '✓', '✔', '✅', 'x', 'yes', 'true', '1', 'نعم'}
CHOICE_BOX = re.compile(r'(<span class="[^"]*\b(?:cb|checkbox|check)\b[^"]*"[^>]*>)\s*\{\{\s*([^{}\n]{1,60}?)\s*\}\}\s*(</span>)')


def blank_names(html: str) -> list:
    """The distinct blanks of a design, in the order they first appear (as plain text, not HTML-escaped)."""
    from html import unescape
    seen = []
    for name in BLANK.findall(html or ''):
        name = unescape(name)
        if name not in seen:
            seen.append(name)
    return seen


def render_design(html: str, values: dict | None = None, marks: bool = False) -> str:
    """The design with each {{blank}} replaced: by its value (escaped), by a dotted line when it has none, or, for a
    template on show (`marks`), by a highlighted field. The design itself was made safe by `clean_html`."""
    from html import unescape
    values = values or {}

    if not marks:
        # A choice box the design already draws (a bordered <span class="cb">): inside it only a tick or nothing, never a
        # second box (☐) nor a dotted line.
        def box(match):
            value = str(values.get(unescape(match.group(2)), '')).strip().lower()
            return f'{match.group(1)}{"&#10003;" if value in CHECKED else "&nbsp;"}{match.group(3)}'
        html = CHOICE_BOX.sub(box, html or '')

    def put(match):
        name = unescape(match.group(1))
        if marks:
            return f'<mark class="blank">{escape(name)}</mark>'
        value = str(values.get(name, '')).strip()
        return f'<bdi>{escape(value)}</bdi>' if value else EMPTY            # <bdi>: a date or a number keeps its own direction
    return BLANK.sub(put, html or '')
