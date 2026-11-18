"""The AI makes the company's templates of documents and writes documents from them, on the strongest model (tier
"premium"). Each function here does ONE AI call and returns plain data (never markup that is shown unclean: designs pass
through safehtml). They are run by the jobs of `apps.documents.jobs`, which are charged when queued at the price the person was
shown and give it back when a function raises (an `AIError` with a message safe to show)."""
import logging
import re
from decimal import Decimal

from django.utils.translation import gettext as _

from apps.ai import client
from apps.ai.client import UNTRUSTED_NOTE, AIError, wrap_untrusted

logger = logging.getLogger(__name__)
MAX_INSTRUCTIONS = 2000
LANGUAGE_NAMES = {'en': 'English', 'ar': 'Arabic', 'tr': 'Turkish', 'de': 'German', 'fr': 'French', 'es': 'Spanish',
                  'pt': 'Portuguese', 'it': 'Italian', 'ru': 'Russian', 'zh-hans': 'Simplified Chinese', 'ja': 'Japanese',
                  'ko': 'Korean', 'hi': 'Hindi', 'id': 'Indonesian', 'fa': 'Persian', 'am': 'Amharic'}
TEMPLATE_SERVICE = 'generate_template'
FILL_SERVICE = 'fill_document'
CONTENT_SERVICE = 'generate_document'        # writes or revises a text template/document
IMPORT_SERVICE = 'import_template'
SERVICES = {'letter': 'generate_letter', 'certificate': 'generate_certificate', 'document': 'generate_document'}   # the kinds

SCHEMA = {'type': 'object', 'additionalProperties': False, 'required': ['subject', 'body'],
          'properties': {'subject': {'type': 'string'}, 'body': {'type': 'string'}}}

# The text of a document is plain text with a few line marks, drawn by documents.templatetags.doc_tags.
MARKUP_RULES = (
    'Write it like a professional, compact, orderly business document that fits on as few pages as it can. Plain text '
    'only (no HTML, no markdown other than these line marks): "## " starts the document title (centred, large); "# " '
    'starts a section with a heading; "- " is a bullet; "> " is a small note; "[ ] " / "[x] " is a choice box (several '
    'choices of one question stay on one line). FACTS about the case (numbers, dates, names, addresses, amounts, contact '
    'details) go in a form table, never one paragraph per fact: "Label | {{value}}" or, for short facts, four columns '
    '"Label | {{value}} | Label | {{value}}", one row per line, all the rows of a group together under its heading. '
    'Rows that repeat (items, installments, people) go in a table: the header row, then a line "---", then the rows '
    '(one example row of blanks); put quantities, prices and totals in their own columns. A first line "@narrow" '
    'before a table makes it half the width at the end side (use it for totals); "@plain" removes its borders (use it '
    'for signature and approval areas such as "Name | {{name}} | Signature | ", and for side-by-side layouts). '
    'Paragraphs are separated by one blank line, and every table is its own block with no blank line inside it. '
    'Example of a sales invoice: "## Sales invoice\n\n# Invoice details\n\nInvoice no. | {{invoice no.}} | Date | '
    '{{date}}\nDue date | {{due date}} | Reference | {{reference}}\n\n# Customer\n\nName | {{customer}} | Phone | '
    '{{phone}}\n\n# Items\n\nDescription | Qty | Unit price | Amount\n---\n{{item}} | {{qty}} | {{price}} | '
    '{{amount}}\n\n@narrow\nSubtotal | {{subtotal}}\nTax | {{tax}}\nTotal | {{total}}\n\n> Payment terms: ...". ')
CONTENT_SYSTEM = (
    'You write one official document from the company\'s own template. Reply with JSON only. Follow the template\'s '
    'structure and wording exactly, and replace every {{blank}} with the matching fact from the subscriber\'s '
    'details. Where a fact the document cannot do without was not given, leave a dotted line ".........."; where an '
    'optional fact was not given, remove its row or sentence altogether instead of leaving a dotted line. Do not '
    'invent facts. Write each person in the gender the facts show (from the name or the pronoun given) and never both '
    'forms with a slash; if it cannot be told use the plain masculine wording. Mark the right choice '
    'boxes with "[x]" and leave the others "[ ]". ' + MARKUP_RULES +
    'Do not write a line naming the addressee (it is printed above the text from the recipient field), nor the date. '
    'Write in the template\'s language. ' + 'Write every amount of money with thousands separators and two decimals, like 1,000.00 followed by its currency (never 1000 or 1000.5). ' + UNTRUSTED_NOTE)


IMPORT_SYSTEM = (
    'You turn a document the company already has (a contract, a form, a certificate...) into a reusable template of the '
    'same document, keeping its wording, order and structure exactly: its title (once, never repeated in the body), '
    'headings, numbered clauses, tables, choice boxes, and its closing blocks (approval, name and signature areas, as '
    'a "@plain" table). A list of fields and values stays a form table, a row of choices stays on one line, the header '
    'fields (number, date, addressee...) stay together at the top as a form table. Everything that is filled in for one particular case (names, numbers, dates, amounts, the ticked '
    'choices, dotted lines or empty spaces to fill) becomes a blank in double braces such as {{employee name}} or '
    '{{start date}} (at most 40 characters, in the document language); keep the fixed text as it is. A table whose '
    'rows differ from case to case keeps its header and one example row of blanks. Reply with JSON only: "subject" '
    'is the document\'s title (with {{blanks}} if it varies), "body" is its text (' + MARKUP_RULES + '), '
    '"language" is its language code among: ' + ', '.join(LANGUAGE_NAMES) + '. Leave out the letterhead, the page '
    'numbers, the stamp and the signature blocks, and the QR code: they are printed separately. '
    + UNTRUSTED_NOTE)
IMPORT_SCHEMA = {'type': 'object', 'additionalProperties': False, 'required': ['subject', 'body', 'language'],
                 'properties': {'subject': {'type': 'string'}, 'body': {'type': 'string'}, 'language': {'type': 'string'}}}


REWRITE_SYSTEM = (
    'You revise one official document. Apply the subscriber\'s instruction to the document and keep everything else '
    'exactly as it is: the structure, the wording of the parts that were not mentioned, every fact and number. Do not '
    'invent facts. Write every amount of money as 1,000.00 (thousands separators, two decimals). Reply with JSON only: "subject" and "body" (' + MARKUP_RULES + '). Keep the language of the document. '
    + UNTRUSTED_NOTE)


DESIGN_RULES = (
    'You are a senior document designer. Design ONE professional, beautiful, orderly A4 business document as a single '
    'self-contained HTML fragment with an inline <style> (no <html>/<body>, no external fonts, images, links, scripts, '
    '@import or url()). It is printed inside the page area of the company\'s own letterhead, whose header and footer are '
    'printed separately and already carry the company\'s logo and contact details: do NOT draw a logo, a letterhead '
    'or a stamp. The width available is about 182 mm; the height flows over as many A4 pages as needed, so avoid fixed '
    'heights and add "break-inside: avoid" to cards, table rows and signature blocks. Use mm, pt or px units. '
    'Use font-family "Almohanad", "Noto Sans Arabic", sans-serif for Arabic and "Noto Sans", sans-serif otherwise; '
    'Almohanad is small, so set Arabic body text at 12-13pt. Use the company\'s brand colours with taste: accents, '
    'section titles, table headers, totals, thin rules. Give it the details a good designer adds: a clear title block, '
    'cards or grids for the parties and the facts, tables with aligned columns, a highlighted total, subtle borders, '
    'status or note boxes, labelled signature lines where the document normally has them. Keep it compact: a short '
    'letter, certificate or notice fits ONE page. Everything that changes from one use to the next is a blank written '
    '{{like this}} in the document language (at most 40 characters, short, distinct); the fixed wording stays as '
    'text. A row that repeats (items, instalments, people) shows three to five sample rows with distinct blanks. A choice '
    'box is written <span class="cb">{{choice name}}</span>: draw the box yourself with CSS (a small bordered square) and put '
    'nothing else inside it; the blank prints a tick when chosen and stays empty otherwise. '
    'Text direction follows the language (set dir on the outer element). ')
DESIGN_SYSTEM = DESIGN_RULES + ('Reply with JSON only: "subject" is the document title (plain text, no blanks), "html" is the '
                                 'fragment. ' + UNTRUSTED_NOTE)
DESIGN_SCHEMA = {'type': 'object', 'additionalProperties': False, 'required': ['subject', 'html'],
                 'properties': {'subject': {'type': 'string'}, 'html': {'type': 'string'}}}
IMPORT_DESIGN_SYSTEM = (
    DESIGN_RULES + 'You are given a document the company already has (pages as a PDF or a picture). Recreate it as faithfully '
    'as you can as the template of that document: the same layout, order, headings, boxes, tables, borders, shading, '
    'colours and wording. Everything filled in for one particular case (names, numbers, dates, amounts, ticked choices, '
    'dotted lines or empty spaces to fill) becomes a blank; the fixed text stays exactly. Do not copy the letterhead, '
    'the logo, the page numbers, the QR code or the stamp: they are printed separately. Reply with JSON only: "subject" '
    'is the title of the document, "html" the fragment, "language" its language code among: '
    + ', '.join(LANGUAGE_NAMES) + '. ' + UNTRUSTED_NOTE)
IMPORT_DESIGN_SCHEMA = {'type': 'object', 'additionalProperties': False, 'required': ['subject', 'html', 'language'],
                        'properties': {'subject': {'type': 'string'}, 'html': {'type': 'string'}, 'language': {'type': 'string'}}}
FILL_SYSTEM = (
    'You fill in a document from its details. You are given the names of the blanks of the document and what the '
    'subscriber says about this case. Reply with JSON only: "values", one entry per blank, with its "name" exactly as '
    'given and its "value". Write the values in the language of the document, short, as they should print (dates, '
    'amounts written 1,000.00 with thousands separators and two decimals and with their currency unless the text beside the blank already gives it, names). A blank whose name starts with a choice (a tick box) takes "☑" or "☐". Use "" '
    'for a blank the details do not cover and that is optional; never invent a fact, a number or a name. '
    'A value goes exactly where its blank stands in the text you are given: never repeat the words already written next to it '
    '(if the text says "Dear {{name}}" the value is the name alone, not "Dear" and the name; if it says "{{amount}} USD" the '
    'value has no currency). ' + UNTRUSTED_NOTE)
FILL_SCHEMA = {'type': 'object', 'additionalProperties': False, 'required': ['values'], 'properties': {'values': {
    'type': 'array', 'items': {'type': 'object', 'additionalProperties': False, 'required': ['name', 'value'],
                               'properties': {'name': {'type': 'string'}, 'value': {'type': 'string'}}}}}}


def _identity_brief(profile, language):
    return (f'Company: {profile.name_for(language)}\nBrand colours: primary {profile.primary_color or "#7c3aed"}, '
            f'secondary {profile.secondary_color or "#111827"}\nTone: {profile.tone or "formal"}\n'
            f'Language: {LANGUAGE_NAMES.get(language, "English")} ({"right-to-left" if language in ("ar", "fa") else "left-to-right"})\n')


MONEY_NAME = re.compile(r'راتب|بدل|مبلغ|سعر|إجمالي|اجمالي|المجموع|قيمة|ضريبة|خصم|أجر|رسوم|amount|total|price|salary|allowance|tax|vat|fee|subtotal|discount|balance|payment|cost', re.I)
NOT_MONEY_NAME = re.compile(r'رقم|عدد|مدة|نسبة|تاريخ|كتابة|حروف|number|\bno\b|date|period|rate|percent|days|words|%', re.I)
MONEY_VALUE = re.compile(r'^\s*(\d[\d,]*(?:\.\d{1,2})?)\s*(\D{0,24})$')


def normalize_money(name: str, value: str) -> str:
    """A value of a money blank written 1,000.00: '1200 دولار' -> '1,200.00 دولار'. Other values are left as they are."""
    if not (MONEY_NAME.search(name or '') and not NOT_MONEY_NAME.search(name or '')):
        return value
    match = MONEY_VALUE.match(value or '')
    if not match:
        return value
    try:
        number = Decimal(match.group(1).replace(',', ''))
    except ArithmeticError:
        return value
    suffix = match.group(2).strip()
    return f'{number:,.2f}' + (f' {suffix}' if suffix else '')


def _values_from(result, names):
    data = (result.data or {}).get('values') or []
    found = {str(item.get('name', '')).strip(): str(item.get('value', '')).strip()[:500] for item in data if isinstance(item, dict)}
    return {name: normalize_money(name, found.get(name, '')) for name in names}


def _context_text(html: str, limit: int = 3500) -> str:
    """The words of a design with its blanks marked {{like this}}: what the AI reads to see what stands around each blank."""
    import html as html_lib
    text = re.sub(r'(?is)<style.*?</style>', ' ', html or '')
    text = re.sub(r'(?i)<br\s*/?>|</(p|div|tr|li|h[1-6]|table|section)>', '\n', text)
    text = html_lib.unescape(re.sub(r'<[^>]+>', ' ', text))
    lines = (line.strip() for line in re.sub(r'[ \t\xa0]+', ' ', text).split('\n'))
    return '\n'.join(line for line in lines if line)[:limit]




# --- The calls. Each one is a single AI run; `job` collects the tokens and the cost. ----------------------------------

def _call(job, system, prompt, schema, effort='high'):
    result = client.call_json(system, prompt, schema, tier='premium', effort=effort)
    job.add_usage(result)
    return result.data or {}


def design_html(job, company, name, language, kind, notes='', previous=None):
    """The designed page of a template: (subject, safe html). Raises AIError (nothing is saved here)."""
    from . import safehtml
    prompt = _identity_brief(company, language) + f'Document: {name}\n'
    if previous is not None and previous.html:
        prompt += '\nThe current design, to be redesigned:\n' + previous.html[:30000] + '\n'
    if notes:
        prompt += '\n' + wrap_untrusted('what to design or change', notes[:MAX_INSTRUCTIONS])
    data = _call(job, DESIGN_SYSTEM, prompt, DESIGN_SCHEMA)
    html = safehtml.clean_html(str(data.get('html', '')))
    if not html or not safehtml.blank_names(html):
        raise AIError(_('The design could not be read. You were not charged; please try again.'), 'design without blanks', retry=True)
    return str(data.get('subject', '')).strip()[:300] or name, html


def import_design(job, company, record):
    """The template of an uploaded paper, recreated as a designed page: (subject, html, language). Raises AIError."""
    from apps.library import extract
    from . import safehtml
    try:
        block = extract.block_for(record)
    except Exception as exc:
        logger.warning('Could not read record %s as a template', record.pk, exc_info=True)
        raise AIError(_('This file could not be read.'), f'prepare: {exc}') from exc
    content = [block, {'type': 'text', 'text': 'Recreate this document as a template.'}]
    data = _call(job, IMPORT_DESIGN_SYSTEM, content, IMPORT_DESIGN_SCHEMA)
    html = safehtml.clean_html(str(data.get('html', '')))
    if not html or not safehtml.blank_names(html):
        raise AIError(_('The template could not be read. Please try again.'), 'import without blanks', retry=True)
    language = str(data.get('language', '')).strip().lower()
    return str(data.get('subject', '')).strip()[:300], html, language if language in LANGUAGE_NAMES else ''


def fill_design(job, document, template, company, instructions):
    """Fill a designed template for one document: the AI returns only the values of the blanks. The document keeps a copy of
    the design and its values."""
    from . import safehtml
    names = safehtml.blank_names(template.html)
    prompt = (f'Language: {LANGUAGE_NAMES.get(template.language, "English")}\nCompany: {company.name_for(template.language)}\n'
              f'Addressed to: {document.recipient or "not given"}\nBlanks:\n' + '\n'.join(f'- {n}' for n in names) + '\n\n'
              + 'The text of the document, with its blanks, for context:\n' + _context_text(template.html) + '\n\n'
              + wrap_untrusted('subscriber details', (instructions or '')[:MAX_INSTRUCTIONS]))
    data = _call(job, FILL_SYSTEM, prompt, FILL_SCHEMA, effort='medium')
    values = _values_from(type('R', (), {'data': data}), names)
    if not any(values.values()):
        raise AIError(_('The details could not be read. You were not charged; please try again.'), 'no values', retry=True)
    document.design, document.values, document.subject, document.body = template.html, values, template.subject, ''
    document.written_by_ai = True


def write_from_template(job, document, template, company, instructions):
    """Fill `document` from a text template (subject and body with blanks)."""
    prompt = (f'Language: {LANGUAGE_NAMES.get(template.language, "English")}\nCompany: {company.name_for(template.language)}\n'
              f'Addressed to: {document.recipient or "not given"}\n\n'
              f'The template:\nSubject: {template.subject}\n{template.body}\n\n'
              + wrap_untrusted('subscriber details', (instructions or '')[:MAX_INSTRUCTIONS]))
    data = _call(job, CONTENT_SYSTEM, prompt, SCHEMA, effort='medium')
    body = str(data.get('body', '')).strip()
    if not body:
        raise AIError(_('The text could not be read. You were not charged; please try again.'), 'empty body', retry=True)
    document.subject = str(data.get('subject', ''))[:300]
    document.body = body
    document.written_by_ai = True


def rewrite(job, document, instructions):
    """Revise a text document's subject and body as told."""
    prompt = (f'Language: {LANGUAGE_NAMES.get(document.language, "English")}\n\nThe document:\nSubject: {document.subject}\n'
              f'{document.body}\n\n' + wrap_untrusted('what to change', (instructions or '')[:MAX_INSTRUCTIONS]))
    data = _call(job, REWRITE_SYSTEM, prompt, SCHEMA, effort='medium')
    body = str(data.get('body', '')).strip()
    if not body:
        raise AIError(_('The text could not be read. You were not charged; please try again.'), 'empty body', retry=True)
    document.subject = str(data.get('subject', document.subject))[:300]
    document.body = body
    document.written_by_ai = True


def rewrite_values(job, document, notes):
    """Change the values of a designed document as told."""
    from . import safehtml
    names = safehtml.blank_names(document.design)
    current = '\n'.join(f'- {n}: {document.values.get(n, "")}' for n in names)
    prompt = (f'Language: {LANGUAGE_NAMES.get(document.language, "English")}\nThe blanks and their current values:\n{current}\n\n'
              + wrap_untrusted('what to change', (notes or '')[:MAX_INSTRUCTIONS])
              + '\n\nReturn every blank, with the value changed only where the instruction asks for it.')
    data = _call(job, FILL_SYSTEM, prompt, FILL_SCHEMA, effort='medium')
    document.values = _values_from(type('R', (), {'data': data}), names)
    document.written_by_ai = True
