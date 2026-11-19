"""The HTML of a received message, made safe to show. It is shown in a sandboxed frame that also has a Content-Security-
Policy forbidding scripts and every outside request, so this cleaning is the second wall, not the only one: only a list of
tags and attributes survives, links are plain http(s)/mailto/tel, and pictures are never loaded (nobody can tell that the
message was opened, and no address is tracked)."""
import re
from html import escape
from html.parser import HTMLParser

from apps.documents.safehtml import clean_declarations

TAGS = {'div', 'span', 'p', 'h1', 'h2', 'h3', 'h4', 'h5', 'h6', 'table', 'thead', 'tbody', 'tfoot', 'tr', 'th', 'td', 'ul', 'ol',
        'li', 'strong', 'b', 'em', 'i', 'u', 's', 'br', 'hr', 'small', 'sub', 'sup', 'blockquote', 'pre', 'code', 'center', 'a',
        'font', 'section', 'article', 'header', 'footer', 'caption', 'dl', 'dt', 'dd', 'mark', 'abbr'}
VOID = {'br', 'hr'}
TABLE_ATTRS = {'width': re.compile(r'^\d{1,4}%?$'), 'height': re.compile(r'^\d{1,4}%?$'), 'cellpadding': re.compile(r'^\d{1,3}$'),
               'cellspacing': re.compile(r'^\d{1,3}$'), 'border': re.compile(r'^\d{1,2}$'), 'valign': re.compile(r'^(top|middle|bottom)$'),
               'bgcolor': re.compile(r'^#[0-9a-fA-F]{3,8}$'), 'role': re.compile(r'^presentation$'), 'alt': re.compile(r'^[^<>"]{0,120}$')}
SKIP = {'script', 'style', 'iframe', 'object', 'embed', 'svg', 'math', 'noscript', 'template', 'textarea', 'title', 'head',
        'form', 'select', 'option', 'button', 'audio', 'video', 'canvas', 'applet'}
SIMPLE = {'colspan': re.compile(r'^\d{1,3}$'), 'rowspan': re.compile(r'^\d{1,3}$'), 'dir': re.compile(r'^(ltr|rtl|auto)$'),
          'align': re.compile(r'^(left|right|center|justify)$')}
LINK = re.compile(r'^(https?://|mailto:|tel:)[^\s<>"\']+$', re.I)


class _Cleaner(HTMLParser):
    def __init__(self, template=False):
        super().__init__(convert_charrefs=True)
        self.out, self.skip, self.images, self.template = [], 0, 0, template

    def handle_starttag(self, tag, attrs):
        if tag == 'img':
            # In a template the one picture allowed is the company logo (the blank {{logo}}); nothing else is ever loaded.
            src = dict(attrs).get('src', '').strip()
            if self.template and not self.skip and re.fullmatch(r'\{\{\s*logo\s*\}\}', src):
                kept = ['src="{{logo}}"']
                for name, value in attrs:
                    value = (value or '').strip()
                    if name == 'style' and (value := clean_declarations(value)):
                        kept.append(f'style="{escape(value, quote=True)}"')
                    elif name in TABLE_ATTRS and TABLE_ATTRS[name].match(value):
                        kept.append(f'{name}="{escape(value, quote=True)}"')
                self.out.append(f'<img {" ".join(kept)}>')
            else:
                self.images += 1
            return
        if tag in SKIP:
            self.skip += 1
            return
        if self.skip or tag not in TAGS:
            return
        kept = []
        for name, value in attrs:
            value = (value or '').strip()
            if name == 'style':
                value = clean_declarations(value)
                if value:
                    kept.append(f'style="{escape(value, quote=True)}"')
            elif name in SIMPLE and SIMPLE[name].match(value):
                kept.append(f'{name}="{escape(value, quote=True)}"')
            elif self.template and name in TABLE_ATTRS and TABLE_ATTRS[name].match(value):
                kept.append(f'{name}="{escape(value, quote=True)}"')
            elif tag == 'a' and name == 'href' and (LINK.match(value) or (self.template and re.fullmatch(r'\{\{\s*(website|email|phone)\s*\}\}', value))):
                kept.append(f'href="{escape(value, quote=True)}" target="_blank" rel="noopener noreferrer nofollow"')
        self.out.append(f'<{tag}{" " + " ".join(kept) if kept else ""}>')

    def handle_endtag(self, tag):
        if tag in SKIP:
            self.skip = max(0, self.skip - 1)
        elif not self.skip and tag in TAGS and tag not in VOID:
            self.out.append(f'</{tag}>')

    def handle_data(self, data):
        if not self.skip:
            self.out.append(escape(data, quote=False))


def clean(source: str, template: bool = False):
    """(safe fragment, number of pictures left out). With `template`, table attributes and the {{logo}} picture are kept."""
    parser = _Cleaner(template)
    parser.feed(source or '')
    parser.close()
    return ''.join(parser.out).strip(), parser.images


def from_text(text: str) -> str:
    """A plain-text message as HTML: escaped, line breaks kept, web addresses made into links."""
    safe = escape(text or '')
    safe = re.sub(r'(https?://[^\s<>"\']+)', lambda m: f'<a href="{m.group(1)}" target="_blank" rel="noopener noreferrer nofollow">{m.group(1)}</a>', safe)
    return f'<div dir="auto" style="white-space:pre-wrap">{safe}</div>'


FRAME_CSP = "default-src 'none'; style-src 'unsafe-inline'; base-uri 'none'; form-action 'none'"


def frame_document(fragment: str) -> str:
    """The page placed in the frame's `srcdoc`."""
    return (f'<!doctype html><meta charset="utf-8"><meta http-equiv="Content-Security-Policy" content="{FRAME_CSP}">'
            '<base target="_blank"><style>body{margin:0;padding:1.1rem 1.3rem;font:15px/1.65 system-ui,"Noto Sans Arabic",sans-serif;color:#18181b;'
            'overflow-wrap:anywhere}a{color:#6d28d9}table{max-width:100%}blockquote{margin:.5em 0;padding-inline-start:.8em;'
            'border-inline-start:3px solid #d4d4d8;color:#52525b}</style><body dir="auto">' + fragment)
