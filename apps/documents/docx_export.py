"""An issued document as a Word file (.docx) the member can edit. The page is the same HTML the PDF is made from (a designed
page with its own CSS, or a text document), so this reads that HTML and its style rules and writes Word's own parts:
paragraphs and runs with their colour, size, weight and direction, tables with their shading, borders, column widths and
merged cells (a flex row or a grid becomes a table), bullet lists and the signature lines (blank lines to sign by hand). What Word cannot say (gradients,
shadows, rounded corners, absolute positions) is left out; the words and the structure are kept."""
import io
import re
from html.parser import HTMLParser

from docx import Document as Docx
from docx.enum.text import WD_ALIGN_PARAGRAPH
from docx.oxml import OxmlElement
from docx.oxml.ns import qn
from docx.shared import Cm, Pt, RGBColor

VOID = {'br', 'hr', 'img', 'col', 'input'}
BLOCKS = {'div', 'p', 'h1', 'h2', 'h3', 'h4', 'h5', 'h6', 'table', 'ul', 'ol', 'li', 'blockquote', 'section', 'article', 'header',
          'footer', 'aside', 'main', 'dl', 'dt', 'dd', 'figure', 'figcaption', 'hr', 'caption', 'pre'}
SKIP = {'style', 'script', 'head', 'title'}
HEADING_PT = {'h1': 20, 'h2': 16, 'h3': 14, 'h4': 12.5, 'h5': 11.5, 'h6': 11}
INHERITED = ('color', 'font-size', 'font-weight', 'font-style', 'text-decoration', 'text-align', 'direction', 'line-height')
NAMED = {'black': '000000', 'white': 'FFFFFF', 'red': 'FF0000', 'green': '008000', 'blue': '0000FF', 'gray': '808080', 'grey': '808080',
         'silver': 'C0C0C0', 'orange': 'FFA500', 'yellow': 'FFFF00', 'navy': '000080', 'maroon': '800000', 'purple': '800080',
         'teal': '008080', 'lightgray': 'D3D3D3', 'lightgrey': 'D3D3D3', 'darkgray': 'A9A9A9', 'transparent': ''}
BASE_PT = 11


# Word is strict about the order of the parts inside a paragraph, run, cell or table property block.
ORDER = {
    'pPr': ['pStyle', 'keepNext', 'keepLines', 'pageBreakBefore', 'framePr', 'widowControl', 'numPr', 'suppressLineNumbers', 'pBdr', 'shd',
            'tabs', 'suppressAutoHyphens', 'kinsoku', 'wordWrap', 'overflowPunct', 'topLinePunct', 'autoSpaceDE', 'autoSpaceDN', 'bidi',
            'adjustRightInd', 'snapToGrid', 'spacing', 'ind', 'contextualSpacing', 'mirrorIndents', 'suppressOverlap', 'jc',
            'textDirection', 'textAlignment', 'textboxTightWrap', 'outlineLvl', 'divId', 'cnfStyle', 'rPr', 'sectPr', 'pPrChange'],
    'rPr': ['rStyle', 'rFonts', 'b', 'bCs', 'i', 'iCs', 'caps', 'smallCaps', 'strike', 'dstrike', 'outline', 'shadow', 'emboss', 'imprint',
            'noProof', 'snapToGrid', 'vanish', 'webHidden', 'color', 'spacing', 'w', 'kern', 'position', 'sz', 'szCs', 'highlight', 'u',
            'effect', 'bdr', 'shd', 'fitText', 'vertAlign', 'rtl', 'cs', 'em', 'lang', 'eastAsianLayout', 'specVanish', 'oMath'],
    'tcPr': ['cnfStyle', 'tcW', 'gridSpan', 'hMerge', 'vMerge', 'tcBorders', 'shd', 'noWrap', 'tcMar', 'textDirection', 'tcFitText', 'vAlign', 'hideMark'],
    'tblPr': ['tblStyle', 'tblpPr', 'tblOverlap', 'bidiVisual', 'tblStyleRowBandSize', 'tblStyleColBandSize', 'tblW', 'jc', 'tblCellSpacing',
              'tblInd', 'tblBorders', 'shd', 'tblLayout', 'tblCellMar', 'tblLook'],
}


def put(parent, child):
    """Add `child` to `parent` where the schema wants it (replacing one of the same kind)."""
    order = ORDER[parent.tag.split('}')[1]]
    name = child.tag.split('}')[1]
    for existing in parent.findall(child.tag):
        parent.remove(existing)
    rank = order.index(name)
    for sibling in parent:
        sibling_name = sibling.tag.split('}')[1]
        if sibling_name in order and order.index(sibling_name) > rank:
            sibling.addprevious(child)
            return child
    parent.append(child)
    return child


class Node:
    def __init__(self, tag, attrs, parent=None):
        self.tag, self.attrs, self.parent, self.children = tag, dict(attrs), parent, []
        self.text = None            # for a text node
        self.style = {}

    @property
    def classes(self):
        return (self.attrs.get('class') or '').split()


class _Tree(HTMLParser):
    def __init__(self):
        super().__init__(convert_charrefs=True)
        self.root = Node('root', {})
        self.cur, self.skip, self.css = self.root, 0, []

    def handle_starttag(self, tag, attrs):
        if tag in SKIP:
            self.skip += 1
            self._in_style = tag == 'style'
            return
        if self.skip:
            return
        node = Node(tag, [(k, v or '') for k, v in attrs], self.cur)
        self.cur.children.append(node)
        if tag not in VOID:
            self.cur = node

    def handle_startendtag(self, tag, attrs):
        self.handle_starttag(tag, attrs)
        if tag not in VOID and not self.skip and self.cur.tag == tag:
            self.cur = self.cur.parent

    def handle_endtag(self, tag):
        if tag in SKIP:
            self.skip = max(0, self.skip - 1)
            return
        if self.skip or tag in VOID:
            return
        node = self.cur
        while node is not self.root and node.tag != tag:
            node = node.parent
        if node is not self.root:
            self.cur = node.parent

    def handle_data(self, data):
        if self.skip:
            if getattr(self, '_in_style', False):
                self.css.append(data)
            return
        text = Node('#text', {}, self.cur)
        text.text = data
        self.cur.children.append(text)


# ── CSS ────────────────────────────────────────────────────────────────────

def declarations(text):
    out = {}
    for part in (text or '').split(';'):
        if ':' in part:
            name, value = part.split(':', 1)
            out[name.strip().lower()] = value.strip()
    return out


def parse_rules(css):
    """[(selector pieces, declarations)] in order: every selector of a rule list is its own entry, with the page scope removed."""
    css = re.sub(r'/\*.*?\*/', '', '\n'.join(css), flags=re.S)
    rules = []
    for selectors, body in re.findall(r'([^{}]+)\{([^{}]*)\}', css):
        if selectors.strip().startswith('@'):
            continue
        decl = declarations(body)
        for sel in selectors.split(','):
            sel = re.sub(r'^\s*\.dh\b\s*', '', sel.strip()).strip()
            if ':' in sel:                      # pseudo-classes and elements are not drawn
                continue
            rules.append((re.split(r'\s*(>|\s)\s*', sel) if sel else [], decl))
    return rules


def _simple_match(node, simple):
    m = re.fullmatch(r'([a-zA-Z][\w-]*)?((?:\.[\w-]+)*)(?:#[\w-]+)?\*?', simple)
    if not m:
        return False
    tag, classes = m.group(1), [c for c in m.group(2).split('.') if c]
    return (not tag or tag == node.tag) and all(c in node.classes for c in classes)


def matches(node, pieces):
    """A selector made of simple parts joined by spaces (descendant) or > (child)."""
    parts = [p for p in pieces if p not in ('', ' ')]
    if not parts:
        return False
    if not _simple_match(node, parts[-1]):
        return False
    rest, cur = parts[:-1], node.parent
    while rest:
        combinator = '>' if rest[-1] == '>' else ' '
        if combinator == '>':
            rest.pop()
        if not rest:
            return False
        want = rest.pop()
        if combinator == '>':
            if cur is None or not _simple_match(cur, want):
                return False
            cur = cur.parent
        else:
            while cur is not None and not _simple_match(cur, want):
                cur = cur.parent
            if cur is None:
                return False
            cur = cur.parent
    return True


def length_pt(value, parent_pt=BASE_PT):
    m = re.fullmatch(r'(-?[\d.]+)\s*(px|pt|em|rem|%|cm|mm)?', (value or '').strip())
    if not m:
        return None
    n, unit = float(m.group(1)), m.group(2) or 'px'
    return {'px': n * .75, 'pt': n, 'em': n * parent_pt, 'rem': n * BASE_PT, '%': n / 100 * parent_pt, 'cm': n * 28.35, 'mm': n * 2.835}[unit]


def color_hex(value):
    value = (value or '').strip().lower()
    m = re.fullmatch(r'#([0-9a-f]{3})', value)
    if m:
        return ''.join(c * 2 for c in m.group(1)).upper()
    m = re.fullmatch(r'#([0-9a-f]{6})', value)
    if m:
        return m.group(1).upper()
    m = re.fullmatch(r'rgba?\(\s*(\d+)[\s,]+(\d+)[\s,]+(\d+)(?:[\s,/]+([\d.]+))?\s*\)', value)
    if m:
        if m.group(4) is not None and float(m.group(4)) == 0:
            return ''
        return '%02X%02X%02X' % tuple(min(255, int(m.group(i))) for i in (1, 2, 3))
    return NAMED.get(value, '')


def first_color(value):
    """The colour in a `background` or `border` shorthand."""
    for token in re.findall(r'#[0-9a-fA-F]{3,6}|rgba?\([^)]*\)|[a-zA-Z]+', value or ''):
        found = color_hex(token)
        if found:
            return found
    return ''


def resolve(node, rules, parent_style):
    """The style of an element: what it inherits, the rules that match it (in order), then its own style attribute."""
    style = {k: v for k, v in parent_style.items() if k in INHERITED}
    tag = node.tag
    if tag in HEADING_PT:
        style.setdefault('font-size', f'{HEADING_PT[tag]}pt')
        style['font-weight'] = 'bold'
    if tag in ('b', 'strong', 'th'):
        style['font-weight'] = 'bold'
    if tag in ('i', 'em'):
        style['font-style'] = 'italic'
    if tag in ('u', 'ins'):
        style['text-decoration'] = 'underline'
    if tag == 'small':
        style['font-size'] = '9pt'
    if node.attrs.get('dir') in ('rtl', 'ltr'):
        style['direction'] = node.attrs['dir']
    if node.attrs.get('align') in ('left', 'right', 'center', 'justify'):
        style['text-align'] = node.attrs['align']
    for pieces, decl in rules:
        if matches(node, pieces):
            style.update(decl)
    style.update(declarations(node.attrs.get('style')))
    own = {k: v for k, v in style.items() if k not in INHERITED or v is not None}
    node.style = own
    return own


def annotate(node, rules, parent_style):
    if node.tag != '#text':
        style = resolve(node, rules, parent_style)
        for child in node.children:
            annotate(child, rules, style)


# ── writing ────────────────────────────────────────────────────────────────

def _shade(element_pr, fill):
    shd = OxmlElement('w:shd')
    shd.set(qn('w:val'), 'clear'); shd.set(qn('w:color'), 'auto'); shd.set(qn('w:fill'), fill)
    put(element_pr, shd)


def _border_element(side, width_pt, color, val='single'):
    el = OxmlElement(f'w:{side}')
    el.set(qn('w:val'), val); el.set(qn('w:sz'), str(max(2, min(96, round(width_pt * 8))))); el.set(qn('w:space'), '0'); el.set(qn('w:color'), color or '000000')
    return el


def borders_of(style):
    """{'top': (pt, color), ...} from border / border-top / ... declarations (none when there is no visible border)."""
    found = {}
    for side in ('top', 'right', 'bottom', 'left'):
        value = style.get(f'border-{side}') or style.get('border') or ''
        if side in ('left', 'right') and style.get(f'border-inline-{"start" if side == "left" else "end"}'):
            value = style[f'border-inline-{"start" if side == "left" else "end"}']
        if not value or re.search(r'\bnone\b|\bhidden\b', value) or value.strip() == '0':
            continue
        width = next((length_pt(t) for t in value.split() if re.fullmatch(r'[\d.]+(px|pt)?', t)), 0.75) or 0.75
        found[side] = (width, first_color(value) or '000000')
    return found


class Writer:
    def __init__(self, rtl_default, font):
        self.doc = Docx()
        self.rtl_default, self.font = rtl_default, font
        section = self.doc.sections[0]
        section.page_width, section.page_height = Cm(21), Cm(29.7)
        for side in ('left_margin', 'right_margin'):
            setattr(section, side, Cm(2))
        section.top_margin = section.bottom_margin = Cm(2)
        normal = self.doc.styles['Normal']
        normal.font.name, normal.font.size = font, Pt(BASE_PT)
        rpr = normal.element.get_or_add_rPr()
        fonts = rpr.find(qn('w:rFonts')) if rpr.find(qn('w:rFonts')) is not None else OxmlElement('w:rFonts')
        for attr in ('w:ascii', 'w:hAnsi', 'w:cs', 'w:eastAsia'):
            fonts.set(qn(attr), font)
        if fonts.getparent() is None:
            rpr.append(fonts)
        normal.paragraph_format.space_after = Pt(0)

    # paragraphs and runs
    def paragraph(self, container, style, node=None):
        para = container.add_paragraph()
        rtl = (style.get('direction') or ('rtl' if self.rtl_default else 'ltr')) == 'rtl'
        ppr = para._p.get_or_add_pPr()
        if rtl:
            put(ppr, OxmlElement('w:bidi'))
        align = (style.get('text-align') or 'start').strip()
        mapped = {'center': WD_ALIGN_PARAGRAPH.CENTER, 'justify': WD_ALIGN_PARAGRAPH.JUSTIFY}.get(align)
        if align in ('left', 'right'):
            physical_right = align == 'right'
            mapped = WD_ALIGN_PARAGRAPH.LEFT if (physical_right == rtl) else WD_ALIGN_PARAGRAPH.RIGHT   # in a right-to-left paragraph "left" is the end
        if mapped is not None:
            para.alignment = mapped
        before, after = length_pt(style.get('margin-top')), length_pt(style.get('margin-bottom'))
        if before:
            para.paragraph_format.space_before = Pt(min(before, 36))
        if after:
            para.paragraph_format.space_after = Pt(min(after, 36))
        line = style.get('line-height', '')
        if re.fullmatch(r'[\d.]+', line):
            para.paragraph_format.line_spacing = max(1.0, min(2.5, float(line)))
        shade = color_hex(style.get('background-color')) or first_color(style.get('background') or '') if 'gradient' not in (style.get('background') or '') else ''
        if shade:
            _shade(ppr, shade)
        edges = borders_of(style)
        if edges:
            pbdr = OxmlElement('w:pBdr')
            for side in ('top', 'left', 'bottom', 'right'):
                if side in edges:
                    pbdr.append(_border_element(side, *edges[side]))
            put(ppr, pbdr)
        para._rtl = rtl
        return para

    def run(self, para, text, style, rtl):
        if not text:
            return
        run = para.add_run(text)
        pt = length_pt(style.get('font-size'))
        run.font.size = Pt(max(6, min(60, pt))) if pt else Pt(BASE_PT)
        run.bold = (style.get('font-weight', '') in ('bold', 'bolder', '600', '700', '800', '900')) or None
        run.italic = (style.get('font-style') == 'italic') or None
        run.underline = ('underline' in style.get('text-decoration', '')) or None
        col = color_hex(style.get('color'))
        if col:
            run.font.color.rgb = RGBColor.from_string(col)
        rpr = run._r.get_or_add_rPr()
        if rtl:
            put(rpr, OxmlElement('w:rtl'))
            if run.bold:
                put(rpr, OxmlElement('w:bCs'))
            fonts = rpr.find(qn('w:rFonts'))
            if fonts is None:
                fonts = put(rpr, OxmlElement('w:rFonts'))
            fonts.set(qn('w:cs'), self.font)

    def inline(self, para, node, rtl):
        for child in node.children:
            if child.tag == '#text':
                text = re.sub(r'[ \t\r\n\f]+', ' ', child.text)
                if text.strip() or (text and para.runs):
                    self.run(para, text.replace('\xa0', ' '), node.style, rtl)
            elif child.tag == 'br':
                para.add_run().add_break()
            elif child.tag in BLOCKS or child.tag == 'table':
                continue
            else:
                cb = 'cb' in child.classes or 'checkbox' in child.classes
                if cb:
                    inner = ''.join(c.text or '' for c in child.children if c.tag == '#text')
                    self.run(para, '☑' if re.search(r'[✓✔☑☒xX]', inner) else '☐', child.style, rtl)
                else:
                    self.inline(para, child, rtl)

    # blocks
    def has_blocks(self, node):
        return any(c.tag in BLOCKS or c.tag == 'table' for c in node.children if c.tag != '#text') or self.layout_kind(node)

    def layout_kind(self, node):
        display = node.style.get('display', '')
        if display in ('flex', 'inline-flex') and 'column' not in node.style.get('flex-direction', ''):
            kids = [c for c in node.children if c.tag != '#text' or (c.text or '').strip()]
            return ('flex', len(kids)) if len(kids) >= 2 else None
        if display in ('grid', 'inline-grid'):
            cols = node.style.get('grid-template-columns', '')
            repeat = re.search(r'repeat\(\s*(\d+)', cols)
            n = int(repeat.group(1)) if repeat else len([t for t in re.split(r'\s+(?![^()]*\))', cols.strip()) if t]) if cols else 0
            return ('grid', n) if n >= 2 else None
        return None

    def blocks(self, container, node):
        """Draw the children of `node` into a document, a table cell or the page body: runs of inline content become one
        paragraph, each block child its own part."""
        pending = []

        def flush():
            if any((c.tag != '#text') or (c.text or '').strip() for c in pending):
                holder = Node('div', {}, node)
                holder.style, holder.children = node.style, list(pending)
                para = self.paragraph(container, node.style)
                self.inline(para, holder, para._rtl)
            pending.clear()
        for child in node.children:
            if child.tag == '#text' or child.tag not in BLOCKS and child.tag != 'table':
                pending.append(child)
            else:
                flush()
                self.block(container, child)
        flush()

    def block(self, container, node):
        tag = node.tag
        if tag == 'table':
            return self.table(container, node)
        if tag == 'hr':
            para = self.paragraph(container, {'border-bottom': node.style.get('border-top') or '1px solid #999'})
            return
        if tag in ('ul', 'ol'):
            number = 0
            for item in [c for c in node.children if c.tag == 'li']:
                number += 1
                mark = '•' if tag == 'ul' else f'{number}.'
                para = self.paragraph(container, item.style)
                para.paragraph_format.left_indent = Pt(14)
                para.paragraph_format.first_line_indent = Pt(-14)
                self.run(para, f'{mark} ', item.style, para._rtl)
                self.inline(para, item, para._rtl)
                for nested in [c for c in item.children if c.tag in ('ul', 'ol')]:
                    self.block(container, nested)
            return
        layout = self.layout_kind(node)
        if layout:
            return self.layout_table(container, node, *layout)
        if self.has_blocks(node):
            if self.visible_box(node):
                return self.boxed(container, node)
            return self.blocks(container, node)
        para = self.paragraph(container, node.style)
        before = len(para.runs)
        self.inline(para, node, para._rtl)
        if tag in ('p', 'blockquote', 'li') and not node.style.get('margin-bottom') and not node.style.get('margin'):
            para.paragraph_format.space_after = Pt(4)
        if tag == 'blockquote':
            para.paragraph_format.left_indent = Pt(18)

    def visible_box(self, node):
        s = node.style
        return bool(borders_of(s)) or bool(color_hex(s.get('background-color')) or (s.get('background') and 'gradient' not in s['background'] and first_color(s['background'])))

    def boxed(self, container, node):
        """A div with a border or a background that holds blocks: a one-cell table, so the box is kept."""
        table = self.new_table(container, 1, 1)
        self.style_cell(table.cell(0, 0), node.style)
        self.cell_content(table.cell(0, 0), node)

    def cell_content(self, cell, node):
        first = cell.paragraphs[0]
        self.blocks(cell, node)
        if len(cell.paragraphs) > 1 and not first.text and not first.runs:
            first._p.getparent().remove(first._p)          # the empty paragraph a new cell starts with

    def new_table(self, container, rows, cols):
        table = container.add_table(rows, cols)
        table.autofit = True
        width = OxmlElement('w:tblW'); width.set(qn('w:type'), 'pct'); width.set(qn('w:w'), '5000')
        put(table._tbl.tblPr, width)
        return table

    def style_cell(self, cell, style, node=None):
        tcpr = cell._tc.get_or_add_tcPr()
        bg = style.get('background-color') or style.get('background') or ''
        fill = '' if 'gradient' in bg else (color_hex(bg) or first_color(bg))
        if fill:
            _shade(tcpr, fill)
        edges = borders_of(style)
        if edges:
            tcb = OxmlElement('w:tcBorders')
            for side in ('top', 'left', 'bottom', 'right'):
                if side in edges:
                    tcb.append(_border_element(side, *edges[side]))
            put(tcpr, tcb)
        pad = length_pt(style.get('padding-top') or style.get('padding')) or 0
        if pad:
            mar = OxmlElement('w:tcMar')
            for side in ('top', 'left', 'bottom', 'right'):
                m = OxmlElement(f'w:{side}'); m.set(qn('w:w'), str(int(min(pad, 20) * 20))); m.set(qn('w:type'), 'dxa'); mar.append(m)
            put(tcpr, mar)
        valign = style.get('vertical-align', '')
        if valign in ('middle', 'center'):
            cell.vertical_alignment = 1
        elif valign == 'bottom':
            cell.vertical_alignment = 2

    def layout_table(self, container, node, kind, columns):
        kids = [c for c in node.children if c.tag != '#text' or (c.text or '').strip()]
        n = columns if kind == 'grid' else len(kids)
        rows = -(-len(kids) // n)
        table = self.new_table(container, rows, n)
        for i, kid in enumerate(kids):
            cell = table.cell(i // n, i % n)
            holder = Node('div', {}, node)
            holder.style = {**node.style, **{k: v for k, v in kid.style.items() if k in INHERITED}}
            holder.children = [kid] if kid.tag != '#text' else [kid]
            self.style_cell(cell, kid.style if kid.tag != '#text' else {})
            if kid.tag in BLOCKS or kid.tag == 'table':
                self.cell_content(cell, holder)
            else:
                self.cell_content(cell, holder)

    def table(self, container, node):
        rows = []
        for section in [c for c in node.children if c.tag in ('thead', 'tbody', 'tfoot', 'tr')]:
            rows += [section] if section.tag == 'tr' else [r for r in section.children if r.tag == 'tr']
        grid, widths = {}, {}
        height = len(rows)
        columns = 0
        for r, row in enumerate(rows):
            c = 0
            for cell in [x for x in row.children if x.tag in ('td', 'th')]:
                while (r, c) in grid:
                    c += 1
                colspan = int(re.sub(r'\D', '', cell.attrs.get('colspan', '1')) or 1)
                rowspan = int(re.sub(r'\D', '', cell.attrs.get('rowspan', '1')) or 1)
                grid[(r, c)] = (cell, colspan, rowspan)
                for dr in range(rowspan):
                    for dc in range(colspan):
                        if dr or dc:
                            grid[(r + dr, c + dc)] = None
                columns = max(columns, c + colspan)
                c += colspan
        if not rows or not columns:
            return
        table = self.new_table(container, height, columns)
        table_edges = borders_of(node.style) if node.attrs.get('border', '0') in ('0', '') else {'top': (0.5, '000000'), 'left': (0.5, '000000'), 'bottom': (0.5, '000000'), 'right': (0.5, '000000')}
        for (r, c), value in grid.items():
            if value is None or r >= height:
                continue
            cell_node, colspan, rowspan = value
            cell = table.cell(r, c)
            if colspan > 1 or rowspan > 1:
                cell = cell.merge(table.cell(min(height - 1, r + rowspan - 1), min(columns - 1, c + colspan - 1)))
            style = dict(cell_node.style)
            if not borders_of(style) and table_edges and node.attrs.get('border', '0') not in ('0', ''):
                style['border'] = '0.5pt solid #000'
            self.style_cell(cell, style, cell_node)
            width = cell_node.style.get('width') or cell_node.attrs.get('width', '')
            if width.endswith('%') and r == 0 and colspan == 1:
                tcw = OxmlElement('w:tcW'); tcw.set(qn('w:type'), 'pct'); tcw.set(qn('w:w'), str(int(float(width[:-1]) * 50)))
                put(cell._tc.get_or_add_tcPr(), tcw)
            self.cell_content(cell, cell_node)
        if borders_of(node.style) and not any(borders_of(v[0].style) for v in grid.values() if v):
            tb = OxmlElement('w:tblBorders')
            for side, (w, col) in borders_of(node.style).items():
                tb.append(_border_element(side, w, col))
            put(table._tbl.tblPr, tb)
        spacer = container.add_paragraph()
        spacer.paragraph_format.space_after = Pt(2)


def build(html: str, *, rtl: bool, title: str = '', images=()) -> bytes:
    """The Word file of a page of HTML. `images` are (bytes, width in cm) added after the text."""
    parser = _Tree()
    parser.feed(html or '')
    parser.close()
    rules = parse_rules(parser.css)
    root = parser.root
    annotate(root, rules, {'direction': 'rtl' if rtl else 'ltr'})
    writer = Writer(rtl, 'Tahoma' if rtl else 'Arial')
    doc = writer.doc
    first = doc.paragraphs[0] if doc.paragraphs else None
    writer.blocks(doc, root)
    for data, width in images:
        para = doc.add_paragraph()
        para.add_run().add_picture(io.BytesIO(data), width=Cm(width))
    if first is not None and not first.text and not first.runs and len(doc.paragraphs) > 1:
        first._p.getparent().remove(first._p)
    doc.core_properties.title = title[:250]
    out = io.BytesIO()
    doc.save(out)
    return out.getvalue()
