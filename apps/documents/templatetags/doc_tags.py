import re

from django import template
from django.utils.html import escape
from django.utils.safestring import mark_safe

from ..blanks import BLANK

register = template.Library()


@register.filter
def blank_inline(text):
    """One line of a template (the subject) with each {{blank}} highlighted."""
    html = escape(BLANK.sub(lambda m: f'\0{m.group(1)}\1', text or ''))
    return mark_safe(html.replace('\0', '<mark class="blank">').replace('\1', '</mark>'))


# --- The body of a document: paragraphs, with a few line marks (see generate.MARKUP_RULES) -------------------------

CHOICE = re.compile(r'\[([ xX])\]\s?')


def _boxes(html):
    """Each "[ ]" / "[x]" in a line or a cell becomes a drawn box."""
    return CHOICE.sub(lambda m: f'<span class="box" aria-hidden="true">{"&#9745;" if m.group(1) in "xX" else "&#9744;"}</span>', html)


def _inline(text, marks):
    """Escaped text with its choice boxes; in a template, each {{blank}} is highlighted."""
    if not marks:
        return _boxes(escape(text))
    html = escape(BLANK.sub(lambda m: f'\0{m.group(1)}\1', text))
    return _boxes(html.replace('\0', '<mark class="blank">').replace('\1', '</mark>'))


ROW = re.compile(r'\s\|(?:\s|$)')          # the cell separator of a table row: " | " (also at the end of a line)
NUMBER = re.compile(r'^[\s\d.,:/%+\-$\u0660-\u0669\u066b\u066c]+$')


def _table(lines, marks):
    """Lines of cells separated by " | ". A first line "@narrow" (half width, at the end side) or "@plain" (no
    borders) sets the look; a line "---" after the first row marks it as the header; without it the table is a form
    (label | value, or label | value | label | value) whose odd columns are the labels. Number cells are aligned to
    the end of the column."""
    classes = ['grid']
    while lines and lines[0].strip() in ('@narrow', '@plain'):
        classes.append(lines[0].strip()[1:])
        lines = lines[1:]
    header = len(lines) > 2 and lines[1].strip() == '---'
    rows = [[cell.strip() for cell in ROW.split(line.rstrip() + ' ')] for line in lines if line.strip() != '---']
    if not header:
        classes.append('kv')
        if rows and max(len(r) for r in rows) >= 4:
            classes.append('four')
    out = [f'<table class="{" ".join(classes)}">']

    def cell(tag, text):
        plain = re.sub(r'\{\{[^}]*\}\}', '', text).strip()
        align = ' class="num"' if tag == 'td' and plain and NUMBER.match(plain) else ''
        return f'<{tag}{align}>{_inline(text, marks)}</{tag}>'
    if header:
        out.append('<thead><tr>' + ''.join(cell('th', c) for c in rows[0]) + '</tr></thead>')
        rows = rows[1:]
    out.append('<tbody>' + ''.join('<tr>' + ''.join(cell('td', c) for c in row) + '</tr>' for row in rows) + '</tbody></table>')
    return ''.join(out)


def _block(lines, marks):
    """One block (lines between blank lines) as HTML: a table, a list, a choice list, a heading, or a paragraph."""
    if len([line for line in lines if ROW.search(line)]) >= 1 and all(
            ROW.search(line) or line.strip() in ('---', '@narrow', '@plain') for line in lines):
        return _table(lines, marks)
    html, items, kind = [], [], ''

    def flush():
        nonlocal items, kind
        if items:
            html.append(f'<ul class="{kind}">' + ''.join(items) + '</ul>')
            items, kind = [], ''
    for line in lines:
        stripped = line.strip()
        if stripped.startswith('## '):
            flush()
            html.append(f'<h2 class="title">{_inline(stripped[3:], marks)}</h2>')
        elif stripped.startswith('# '):
            flush()
            html.append(f'<h3 class="sec">{_inline(stripped[2:], marks)}</h3>')
        elif stripped.startswith('> '):
            flush()
            html.append(f'<p class="note">{_inline(stripped[2:], marks)}</p>')
        elif len(CHOICE.findall(stripped)) >= 2:                       # several boxes on one line stay on one line
            flush()
            html.append(f'<p class="choices">{_inline(stripped, marks)}</p>')
        elif stripped.startswith(('[ ] ', '[x] ', '[X] ')):
            if kind != 'boxes':
                flush()
                kind = 'boxes'
            items.append(f'<li>{_inline(stripped, marks)}</li>')
        elif stripped.startswith('- '):
            if kind != 'bullets':
                flush()
                kind = 'bullets'
            items.append(f'<li>{_inline(stripped[2:], marks)}</li>')
        else:
            flush()
            html.append(f'<p>{_inline(stripped, marks)}</p>')
    flush()
    return ''.join(html)


@register.filter
def document_body(text):
    """The text of a document drawn as HTML: headings, bullets, choice boxes, tables and paragraphs."""
    return _render(text, False)


@register.filter
def template_body(text):
    """The same for a template: its {{blanks}} are highlighted."""
    return _render(text, True)


def _render(text, marks):
    blocks = [chunk.split('\n') for chunk in (text or '').replace('\r\n', '\n').strip().split('\n\n') if chunk.strip()]
    return mark_safe('\n'.join(_block([line for line in lines if line.strip()], marks) for lines in blocks))


@register.filter
def has_title(text):
    """The body already carries its own title line ("## ..."), so the subject is not printed again above it."""
    return any(line.startswith('## ') for line in (text or '').replace('\r\n', '\n').split('\n'))
