"""AI work of the company identity, as paid jobs (apps.jobs, kind CALL): create a letterhead as an SVG page, and read the company's
details from a paper it already has. Each is charged when queued at the quote shown and given back when it fails."""
import base64
import io
import logging
import uuid

from django.conf import settings
from django.core.files.base import ContentFile
from django.urls import reverse
from django.utils.translation import gettext as _
from pypdf import PdfReader, PdfWriter

from apps.ai import client
from apps.ai.client import AIError
from apps.core.storage import private_storage
from apps.core.tenancy import company_context
from apps.jobs.models import Job

from . import letterheads, svg

logger = logging.getLogger(__name__)
LETTERHEAD_SERVICE = 'create_letterhead'
DETECT_SERVICE = 'detect_identity'
MAX_NOTE = 500
MAX_PAPER_BYTES = 8 * 1024 * 1024
ENGLISH_NAMES = {'en': 'English', 'ar': 'Arabic', 'tr': 'Turkish', 'de': 'German', 'fr': 'French', 'es': 'Spanish', 'pt': 'Portuguese',
                 'it': 'Italian', 'ru': 'Russian', 'zh-hans': 'Simplified Chinese', 'ja': 'Japanese', 'ko': 'Korean', 'hi': 'Hindi',
                 'id': 'Indonesian', 'fa': 'Persian', 'am': 'Amharic'}

SYSTEM = (
    'You are a senior brand designer. You answer with exactly one SVG document and nothing else: no explanation, no '
    'markdown fences. Use only basic shapes, paths, gradients and text. No scripts, no external images, no external '
    'fonts, no foreignObject. Always set a viewBox. Arabic and English text must render right-to-left and '
    'left-to-right correctly (direction and text-anchor). Make it clean, modern and print-ready. ' + client.UNTRUSTED_NOTE)
LETTERHEAD_BRIEF = (
    'Design an A4 letterhead as a full-page SVG, viewBox="0 0 794 1123": a refined header with the company name and contact '
    'details, a slim footer with the address and registration numbers, and a completely empty white body between them. Leave a clear '
    'empty box of 160x70 at the top start corner for the logo and do not draw any logo yourself.')


def _facts(company) -> str:
    rows = [('Name', company.name), ('Language of the name', company.get_main_language_display()), ('Legal name', company.legal_name),
            ('Address', company.address),
            *((f'Name in {lang}', v.get('name')) for lang, v in (company.other_names or {}).items()),
            ('Commercial registration', company.cr_number), ('Tax number', company.tax_number), ('Phone', company.phone),
            ('Email', company.official_email or company.email), ('Website', company.website),
            ('Primary colour', company.primary_color), ('Secondary colour', company.secondary_color), ('Tone', company.tone)]
    return '\n'.join(f'{label}: {value}' for label, value in rows if value)


# --- A letterhead made by the AI ------------------------------------------------------------------------------------

def queue_letterhead(company, user, expected_points, language, note=''):
    return Job.enqueue(company, Job.Kind.CALL, user, expected_points=expected_points, func='apps.identity.ai.create_letterhead',
                       service=LETTERHEAD_SERVICE, language=language, note=(note or '')[:MAX_NOTE],
                       result_url=reverse('identity:letterheads'))


def create_letterhead(job):
    """The job: one run on the strongest model, a letterhead written in the language; the SVG is cleaned before it is kept."""
    company, language = job.company, job.params['language']
    prompt = (f'{LETTERHEAD_BRIEF} Write every word printed on it in {ENGLISH_NAMES.get(language, "English")}.\n\n'
              f'Company facts:\n{_facts(company)}\n'
              f'Name to print: {company.name_for(language)}\nAddress to print: {company.address_for(language)}\n\n'
              + client.wrap_untrusted('subscriber note', job.params.get('note', '')))
    result = client.complete_text(SYSTEM, prompt, max_tokens=16000, effort='high', tier='premium')
    job.add_usage(result)
    try:
        clean = svg.sanitize(result.data['text'])
    except svg.UnsafeSVG as exc:
        logger.warning('AI returned an unusable SVG for the %s letterhead', language)
        raise AIError(_('The design could not be read. You were not charged; please try again.'), str(exc)) from exc
    with company_context(company):
        letterheads.save(company, language, ContentFile(clean.encode('utf-8')), 'letterhead.svg', 'created')
    return _('Created.')


# --- The company's details read from a paper ---------------------------------------------------------------------------

DETECT_FIELDS = ('name', 'legal_name', 'address', 'cr_number', 'tax_number', 'phone', 'email', 'website')
DETECT_SYSTEM = (
    'You read an official paper of a company (a commercial registration, a tax certificate, a licence, a business card, '
    'a letter) and return the details of the company that issued or owns it. Reply with JSON only. "name" is the '
    'name the company is known by; "legal_name" its full registered name; "address" one address on as many lines as '
    'it has; "cr_number" the commercial registration number; "tax_number" the tax or VAT number; "phone", "email", '
    '"website"; "language" the language code of the name among: ' + ', '.join(ENGLISH_NAMES) + '. Use an empty string '
    'for anything the paper does not say. Never invent a detail. ' + client.UNTRUSTED_NOTE)
DETECT_SCHEMA = {'type': 'object', 'additionalProperties': False, 'required': list(DETECT_FIELDS) + ['language'],
                 'properties': {key: {'type': 'string'} for key in DETECT_FIELDS + ('language',)}}


def prepare_paper(upload):
    """The uploaded paper as a content block (a PDF cut to its first 3 pages, or an image scaled down), or raises ValueError with a
    message safe to show. Nothing is charged for a paper that cannot be used."""
    from apps.library.extract import _image_block
    from apps.library.forms import sniff
    if upload.size > MAX_PAPER_BYTES:
        raise ValueError(_('The file must be smaller than 8 MB.'))
    kind = sniff(upload)
    if kind is None:
        raise ValueError(_('Upload a PDF or an image (PNG, JPG or WebP).'))
    raw = upload.read()
    try:
        if kind == 'application/pdf':
            writer = PdfWriter()
            for page in PdfReader(io.BytesIO(raw)).pages[:3]:
                writer.add_page(page)
            out = io.BytesIO()
            writer.write(out)
            return {'type': 'document', 'source': {'type': 'base64', 'media_type': 'application/pdf', 'data': base64.b64encode(out.getvalue()).decode()}}
        return _image_block(raw)
    except Exception as exc:
        logger.warning('Could not prepare a company paper', exc_info=True)
        raise ValueError(_('This file could not be read.')) from exc


def queue_detect(company, user, expected_points, block):
    """Queue the reading. The prepared paper waits in the company's encrypted storage until the job has read it (then it is deleted)."""
    name = private_storage().save(f'{company.pk}/tmp/detect-{uuid.uuid4().hex}.json', ContentFile(__import__('json').dumps(block).encode()))
    try:
        return Job.enqueue(company, Job.Kind.CALL, user, expected_points=expected_points, func='apps.identity.ai.detect_company',
                           service=DETECT_SERVICE, paper=name)
    except Exception:
        private_storage().delete(name)
        raise


def detect_company(job):
    """The job: read the company's details from the stored paper; they go back to the page in `job.params['result']`."""
    import json
    storage = private_storage()
    name = job.params['paper']
    try:
        with storage.open(name, 'rb') as handle:
            block = json.loads(handle.read())
    finally:
        storage.delete(name)
    result = client.call_json(DETECT_SYSTEM, [block, {'type': 'text', 'text': 'Return the details of the company.'}], DETECT_SCHEMA,
                              tier='premium', effort='low', max_tokens=3000)
    job.add_usage(result)
    data = result.data or {}
    details = {key: str(data.get(key, '')).strip()[:300] for key in DETECT_FIELDS}
    language = str(data.get('language', '')).strip().lower()
    if language in ENGLISH_NAMES and language in dict(settings.LANGUAGES):
        details['main_language'] = language
    if not any(details[key] for key in DETECT_FIELDS):
        raise AIError(_('Nothing about the company could be read from this paper. You were not charged.'))
    job.params = {**job.params, 'result': details, 'paper': ''}
    job.save(update_fields=['params'])
    return _('Done. Check the details below, correct anything that is wrong, then press Continue.')
