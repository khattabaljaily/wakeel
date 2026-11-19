"""Presentations: the price, the saved request, and the paid job that builds the deck.

The slides are built by enjaz-docai (presentation.py) in one of three options (standard, premium, ultra: see its costs.json), in
the company's colours and logo, in the language asked. The price is set by the slide, plus the pages of the document it is built
from. Like every paid action here it is charged when the job is queued, at the quote the person was shown, and goes back if the
job fails. The work runs inside this process (the library), through the AI client."""
import io
import logging
from decimal import ROUND_CEILING, Decimal

from django.core.files.base import ContentFile
from django.db import transaction
from django.urls import reverse
from django.utils.translation import gettext as _
from django.utils.translation import gettext_lazy
from enjaz_docai import presentation as docai_presentation
from enjaz_docai import source as docai_source

from apps.ai.client import AIError
from apps.core.tenancy import company_context
from apps.credits import catalog, guards
from apps.credits import quote as quotes
from apps.credits.charging import can_afford
from apps.docops import ops
from apps.jobs.models import Job

from .models import Presentation

logger = logging.getLogger(__name__)
FUNC = 'apps.presentations.service.run_presentation'
OPTIONS = {Presentation.STANDARD: 'presentation', Presentation.PREMIUM: 'presentation_premium', Presentation.ULTRA: 'presentation_ultra'}
TIER_NOTES = {
    Presentation.STANDARD: gettext_lazy('A good, clear deck, written in one pass.'),
    Presentation.PREMIUM: gettext_lazy('Reviewed and sharpened by a second pass: stronger titles and a tighter story.'),
    Presentation.ULTRA: gettext_lazy('The best we can build: your audience is analysed first, then every designed slide is checked by eye and corrected.'),
}


def option_key(tier):
    return OPTIONS.get(tier, OPTIONS[Presentation.PREMIUM])


# ── the price: the screen and the charge use these same functions ────────────────────────────────────────────────────
def units(tier, slides, source_pages=0):
    """Slides, plus the document's pages counted as the slides they cost (the library's per-page figure), rounded up."""
    spec = catalog.service(option_key(tier))
    extra = Decimal(str(spec.get('source_page_cost_usd', 0))) * source_pages / Decimal(str(spec['measured_cost_usd']))
    return (Decimal(slides) + extra).quantize(Decimal('0.01'), rounding=ROUND_CEILING)


def quote(tier, slides, source_pages=0):
    return quotes.make(option_key(tier), str(units(tier, slides, source_pages)), slides)


def tier_prices(slides=10):
    """[(tier, label, quote for `slides` slides, what it adds)] for the choice before anything is typed."""
    return [(tier, label, quote(tier, slides), TIER_NOTES[tier]) for tier, label in Presentation.TIERS
            if catalog.is_launched(option_key(tier))]


def source_pages_of(record):
    return (ops.page_count(record) or 1) if record else 0


def refusal(company, user, tier, slides, source_pages):
    """The reason a run cannot start now (a message), or ''. Nothing is charged here."""
    if not catalog.is_launched(option_key(tier)):
        return _('This option is not available yet.')
    q = quote(tier, slides, source_pages)
    if guards.blocked_reason(company, user, q.total):
        return _('The service is busy at the moment. Please try again later.')
    if not can_afford(company, user, q):
        return _('Your balance is not enough for this presentation. Top up your wallet and try again.')
    return ''


def start(company, user, presentation, expected_points):
    """Save the request and queue its paid job, charged here at the quote shown (a refused payment raises, and nothing is kept)."""
    pages = source_pages_of(presentation.source)
    with transaction.atomic():
        presentation.company = company
        presentation.source_pages = pages
        presentation.units = units(presentation.tier, presentation.slides, pages)
        presentation.created_by = user
        presentation.status = Presentation.QUEUED
        presentation.save()
        job = Job.enqueue(company, Job.Kind.CALL, user, expected_points=expected_points, func=FUNC,
                          service=option_key(presentation.tier), units=str(presentation.units), pages=presentation.slides,
                          presentation_id=presentation.pk, result_url=reverse('presentations:detail', args=[presentation.pk]))
        presentation.job_id = job.pk
        presentation.save(update_fields=['job_id'])
    return presentation


# ── the job ──────────────────────────────────────────────────────────────────────────────────────────────────────────
def _logo_png(company):
    """The company logo as a PNG of at most 600 px, or None."""
    if not company.logo:
        return None
    try:
        from PIL import Image
        with company.logo.open('rb') as handle, Image.open(handle) as image:
            image = image.convert('RGBA')
            image.thumbnail((600, 600))
            out = io.BytesIO()
            image.save(out, 'PNG')
            return out.getvalue()
    except Exception:
        logger.warning('The logo could not be read; the deck is made without it', exc_info=True)
        return None


def identity_of(company, language):
    """What the deck takes from the company's identity: its name in the deck's language, colours, contact lines."""
    return {'name': company.name_for(language) or company.name, 'primary': company.primary_color, 'secondary': company.secondary_color,
            'website': company.website, 'email': company.official_email or company.email, 'phone': company.phone}


def _source_of(presentation):
    record = presentation.source
    if not record:
        return None, None
    with record.file.storage.open(record.file.name, 'rb') as handle:
        raw = handle.read()
    return (raw if record.is_image else ops._first_pages(raw)), ('photo.jpg' if record.is_image else 'document.pdf')


def _run(presentation, company, job):
    """The work: saves the files and the plan on the presentation; raises AIError on failure."""
    identity = identity_of(company, presentation.language)
    logo = _logo_png(company)
    raw, name = _source_of(presentation)
    usage = ops._usage_collector()
    try:
        result = docai_presentation.build(
            ops._make_chat(usage), presentation.brief.strip(), language=presentation.language, slides=presentation.slides,
            audience=presentation.audience, tone=presentation.tone, source=docai_source.from_file(name, raw) if raw else None,
            identity={**identity, 'logo': logo} if logo else identity, author=identity.get('name', ''), tier=presentation.tier)
    finally:
        ops._record_usage(job, usage)
    pptx, pdf = result.get('pptx'), result.get('pdf')
    if not result.get('ok') or not (pptx and pdf):
        logger.error('A presentation failed (%s)', result.get('code'))
        raise AIError(_('The service had a problem. You were not charged; please try again.'), str(result.get('code')))
    stem = (presentation.title or 'presentation')[:60]
    presentation.pptx.save(f'{stem}.pptx', ContentFile(pptx), save=False)
    presentation.preview.save(f'{stem}.pdf', ContentFile(pdf), save=False)
    presentation.deck = result.get('deck') or {}


def run_presentation(job):
    """The paid job: build one saved presentation and record how it ended. A failure raises (the charge is given back)."""
    with company_context(job.company):
        presentation = Presentation.objects.select_related('source').get(pk=job.params['presentation_id'])
        Presentation.objects.filter(pk=presentation.pk).update(status=Presentation.RUNNING)
        try:
            _run(presentation, job.company, job)
        except Exception as exc:
            Presentation.objects.filter(pk=presentation.pk).update(
                status=Presentation.FAILED, error=(str(exc) if isinstance(exc, AIError) else
                                                   _('The service had a problem. You were not charged; please try again.'))[:300])
            raise
        presentation.status, presentation.error = Presentation.DONE, ''
        presentation.save()
    return _('Done.')
