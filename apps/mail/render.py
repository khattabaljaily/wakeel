"""Putting a message into a template, and the plain-text twin of a message. Nothing here calls the network."""
import base64
import html as html_lib
import re
from html import escape

BLANK = re.compile(r'\{\{\s*([a-z_]+)\s*\}\}')
SAMPLE_BODY = ('<p>Dear Ms. Sara,</p><p>Thank you for your interest. Please find the details of our offer below, and tell us if '
               'you would like to change anything.</p><ul><li>Delivery within 10 days</li><li>Payment by bank transfer</li></ul>'
               '<p>Best regards,<br>The team</p>')
SAMPLE_BODY_AR = ('<p>السيدة سارة المحترمة،</p><p>نشكر لكم اهتمامكم. نرفق لكم تفاصيل عرضنا أدناه، ونرجو إعلامنا إن رغبتم في أي تعديل.</p>'
                  '<ul><li>التسليم خلال 10 أيام</li><li>الدفع بالتحويل المصرفي</li></ul><p>مع أطيب التحيات،<br>فريق العمل</p>')


def company_values(company, language='en'):
    """The company's details for the blanks of a template, in the template's language when the company has them."""
    return {'company': company.name_for(language) or company.name, 'address': company.address_for(language) or '',
            'phone': company.phone, 'email': company.official_email or company.email, 'website': company.website}


def fill(template_html: str, body_html: str, subject: str, values: dict, logo_src: str = '') -> str:
    """The template with its blanks filled: the body as it is (it was cleaned already), everything else escaped. A blank
    the company has no value for becomes empty, so the template never shows a raw {{name}}."""
    def one(match):
        name = match.group(1)
        if name == 'body':
            return body_html
        if name == 'logo':
            return logo_src
        if name == 'subject':
            return escape(subject)
        return escape(str(values.get(name, '') or '')).replace('\n', '<br>')
    page = BLANK.sub(one, template_html)
    return page if logo_src else re.sub(r'<img\b[^>]*\bsrc=""[^>]*>', '', page)       # no logo: no broken picture


def plain_wrapper(body_html: str, rtl: bool) -> str:
    """The look of a message sent without a template: just the body, in the right direction."""
    return f'<div dir="{"rtl" if rtl else "auto"}" style="font-size:15px;line-height:1.6;color:#18181b">{body_html}</div>'


def document(inner: str, rtl: bool = False) -> str:
    """The full page of an e-mail."""
    return (f'<!doctype html><html dir="{"rtl" if rtl else "ltr"}"><head><meta charset="utf-8">'
            '<meta name="viewport" content="width=device-width, initial-scale=1"></head>'
            f'<body style="margin:0;padding:0;background:#ffffff">{inner}</body></html>')


def to_text(body_html: str) -> str:
    """The plain-text version sent next to the HTML (what mail apps without HTML, and spam filters, read)."""
    text = re.sub(r'(?is)<(script|style).*?</\1>', '', body_html or '')
    text = re.sub(r'(?i)</(p|h[1-6]|blockquote)>', '\n\n', text)
    text = re.sub(r'(?i)<br\s*/?>|</(div|li|tr|ul|ol)>', '\n', text)
    text = re.sub(r'(?i)<li[^>]*>', '• ', text)
    text = re.sub(r'(?is)<a [^>]*href="([^"]+)"[^>]*>(.*?)</a>', lambda m: f'{re.sub(r"<[^>]+>", "", m.group(2))} ({m.group(1)})', text)
    text = html_lib.unescape(re.sub(r'<[^>]+>', '', text))
    return re.sub(r'\n{3,}', '\n\n', re.sub(r'[ \t]+\n', '\n', text)).strip()


def _logo_bytes(company):
    if not company.logo:
        return b''
    try:
        with company.logo.storage.open(company.logo.name, 'rb') as f:
            return f.read()
    except (ValueError, OSError):
        return b''


def _kind(data):
    return 'image/png' if data[:4] == b'\x89PNG' else 'image/jpeg' if data[:2] == b'\xff\xd8' else 'image/webp' if data[8:12] == b'WEBP' else ''


def logo_data_uri(company) -> str:
    """The company logo as a data address, for the on-screen preview only (a sent message carries it as an attachment)."""
    data = _logo_bytes(company)
    kind = _kind(data)
    return f'data:{kind};base64,{base64.b64encode(data).decode()}' if kind else ''


def logo_part(company):
    """(bytes, 'image/png') of the logo for the sent message, or None."""
    data = _logo_bytes(company)
    kind = _kind(data)
    return (data, kind) if kind else None
