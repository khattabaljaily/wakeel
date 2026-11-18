"""The brand studio: the elements, their prices, and the paid job that designs one.

Every element comes from enjaz-docai (brand.py): only the logo uses the AI model, the rest is designed from the brand kit with real
fonts and layouts. Prices are fixed values set by the owner (credits/pricing_v1.json `price_overrides`), charged when the job is
queued at the quote shown and given back if it fails. A whole kit costs 20% less."""
import base64
import io
import logging
from decimal import Decimal

from django.core.files.base import ContentFile
from django.db import close_old_connections, transaction
from django.urls import reverse
from django.utils.translation import gettext as _
from enjaz_docai import brand
from PIL import Image

from apps.ai.client import AIError
from apps.core.tenancy import company_context
from apps.credits import catalog
from apps.credits import quote as quotes
from apps.docops import ops
from apps.jobs.models import Job

from .models import BrandAsset, BrandFile, BrandKit

logger = logging.getLogger(__name__)
FUNC = 'apps.brand.service.run_asset'
GROUPS = brand.GROUPS
ELEMENTS = brand.ELEMENTS
PERSON_ELEMENTS = ('business_card', 'email_signature')
NEEDS_SYMBOL = ('logo_variants',)
KIT_DISCOUNT = Decimal(str(catalog.load().get('brand_kit_discount', 0.2)))
MAX_FILE = 25 * 1024 * 1024


def option_key(element, tier):
    return brand.option_key(element, tier)


def units(bundle=False):
    """The share of the price paid: 1, or 0.8 for a design that is part of the whole kit."""
    return (Decimal(1) - KIT_DISCOUNT) if bundle else Decimal(1)


def quote(element, tier, bundle=False):
    """The quote of one design: the screen and the charge use this same function."""
    return quotes.make(option_key(element, tier), str(units(bundle)), 1)


def kit_total(tier):
    """What the whole kit costs in a tier, with the discount (points)."""
    return sum(quote(e, tier, True).total for e in ELEMENTS)


def get_kit():
    kit = BrandKit.objects.first()
    return kit or BrandKit.objects.create()


def _logo_png(company):
    """The company's own uploaded logo as PNG bytes, or b'' (it carries the other pieces when no symbol was designed)."""
    if not company.logo:
        return b''
    try:
        with company.logo.open('rb') as handle, Image.open(handle) as im:
            out = io.BytesIO()
            im.convert('RGBA').save(out, 'PNG')
            return out.getvalue()
    except Exception:
        return b''


def kit_dict(company, kit) -> dict:
    """What enjaz-docai is told about the brand: who it is, and what is already decided."""
    language = company.main_language or 'en'
    alt = next((v.get('name') for v in (company.other_names or {}).values() if v.get('name')), '')
    palette = dict(kit.palette or {})
    logo_b64 = ''
    if not kit.symbol:
        png = _logo_png(company)
        logo_b64 = base64.b64encode(png).decode() if png and len(png) < 280_000 else ''
    return {'logo_png_b64': logo_b64, 'name': company.name_for(language) or company.name, 'name_alt': alt, 'language': language,
            'tone': company.tone, 'primary': company.primary_color, 'secondary': company.secondary_color,
            'palette': {'primary': palette.get('primary') or company.primary_color, 'secondary': palette.get('secondary') or company.secondary_color,
                        'accent': palette.get('accent')},
            'pairing': kit.pairing, 'symbol': kit.symbol, 'keywords': kit.keywords, 'personality': kit.personality,
            'contacts': {'phone': company.phone, 'email': company.official_email or company.email, 'website': company.website,
                         'address': company.address_for(language), 'cr': company.cr_number, 'tax': company.tax_number}}


def latest(element):
    """The newest finished purchase of an element (any tier), or None."""
    return BrandAsset.objects.filter(element=element, status=BrandAsset.DONE).first()


def refusal(company, element, tier):
    """Why this cannot start now (a message), or ''. Nothing is charged here."""
    if not catalog.is_launched(option_key(element, tier)):
        return _('This option is not available yet.')
    if not company.name:
        return _('Add your company name in the company details first.')
    if element in NEEDS_SYMBOL and not get_kit().symbol:
        return _('Create and choose your logo first: its versions are made from it.')
    return ''


def start(company, user, element, tier, expected_points=None, person=None, note='', bundle=False):
    """Save the request and queue its paid job (charged here at the quote shown: a refused payment raises, and nothing is kept).
    Returns the asset."""
    with transaction.atomic():
        asset = BrandAsset.objects.create(company=company, element=element, tier=tier, person=person or {}, note=(note or '')[:500],
                                          bundled=bundle, created_by=user)
        job = Job.enqueue(company, Job.Kind.CALL, user, expected_points=expected_points, func=FUNC, service=option_key(element, tier),
                          units=str(units(bundle)), pages=1, asset_id=asset.pk, result_url=reverse('brand:detail', args=[asset.pk]))
        asset.job_id = job.pk
        asset.save(update_fields=['job_id'])
    return asset


# ── the job ──────────────────────────────────────────────────────────────────────────────────────────────────────────
def _run(asset, company, job):
    """The work: saves the files (and for the logo its concepts) on the asset; raises AIError on failure."""
    kit = get_kit()
    data = kit_dict(company, kit)
    usage = ops._usage_collector()
    chat = ops._make_chat(usage) if asset.element == 'logo' else None
    try:
        res = brand.build(asset.element, asset.tier, data, chat, workers=3, thread_cleanup=close_old_connections,
                          person=asset.person or None, note=asset.note)
    finally:
        ops._record_usage(job, usage)
    if not res.get('ok') or not res.get('files'):
        logger.error('A brand element failed (%s)', res.get('code'))
        raise AIError(_('The service had a problem. You were not charged; please try again.'), str(res.get('code')))
    asset.design = {k: res[k] for k in ('concepts', 'palette', 'pairing', 'keywords', 'personality') if k in res}
    asset.save(update_fields=['design'])
    for name, content in res['files'].items():
        if len(content) <= MAX_FILE:
            f = BrandFile(company=company, asset=asset, name=name, size=len(content))
            f.file.save(name, ContentFile(content), save=False)
            f.save()


def run_asset(job):
    """The paid job: design one saved element, and record how it ended. A failure raises (the charge is given back)."""
    with company_context(job.company):
        asset = BrandAsset.objects.get(pk=job.params['asset_id'])
        BrandAsset.objects.filter(pk=asset.pk).update(status=BrandAsset.RUNNING)
        try:
            _run(asset, job.company, job)
        except Exception as exc:
            BrandFile.objects.filter(asset_id=asset.pk).delete()
            BrandAsset.objects.filter(pk=asset.pk).update(
                status=BrandAsset.FAILED, error=(str(exc) if isinstance(exc, AIError) else
                                                 _('The service had a problem. You were not charged; please try again.'))[:300])
            raise
        BrandAsset.objects.filter(pk=asset.pk).update(status=BrandAsset.DONE, error='')
    return _('Done.')


# ── choosing the logo, and the rest of the kit ───────────────────────────────────────────────────────────────────────
def choose_concept(company, asset, n):
    """The owner chooses one of the logo concepts: its symbol, colours and fonts become the brand kit, and the logo and the colours go to the
    company's identity (what letters, documents and presentations are built from). Returns '' or an error message."""
    concepts = {c['n']: c for c in (asset.design or {}).get('concepts', [])}
    if asset.element != 'logo' or asset.status != BrandAsset.DONE or n not in concepts:
        return _('This logo cannot be chosen.')
    design = asset.design
    kit = get_kit()
    palette = design.get('palette') or {}
    kit.symbol, kit.chosen_name = concepts[n]['symbol'], concepts[n].get('name', '')
    kit.palette = {k: palette.get(k) for k in ('primary', 'secondary', 'accent') if palette.get(k)}
    kit.pairing, kit.keywords, kit.personality = design.get('pairing', ''), design.get('keywords') or [], design.get('personality', '')
    kit.save()
    logo = BrandFile.objects.filter(asset=asset, name=f'c{n}_logo-horizontal.png').first()
    if logo:
        with logo.file.storage.open(logo.file.name, 'rb') as handle:
            company.logo.save('logo.png', ContentFile(handle.read()), save=False)
    company.primary_color = kit.palette.get('primary') or company.primary_color
    company.secondary_color = kit.palette.get('secondary') or company.secondary_color
    company.save()
    BrandAsset.objects.filter(pk=asset.pk).update(chosen=n)
    return ''


def rest_of_kit(company, user, tier, expected_points):
    """Order every element that is not made yet, at the kit's discount. The whole order is one payment: the total shown is checked
    first, and each piece is then charged its own quote (so a kit is never half-bought). Returns (assets, '' or an error message)."""
    kit = get_kit()
    if not kit.symbol:
        return [], _('Choose your logo first.')
    todo = [e for e in ELEMENTS if e != 'logo' and not BrandAsset.objects.filter(
        element=e, status__in=[BrandAsset.DONE, BrandAsset.QUEUED, BrandAsset.RUNNING]).exists()]
    if not todo:
        return [], _('Every element of the kit is already made.')
    for e in todo:
        if (reason := refusal(company, e, tier)):
            return [], reason
    total = sum(quote(e, tier, True).total for e in todo)
    if expected_points is not None and int(expected_points) != total:
        from apps.credits.charging import PriceChanged
        raise PriceChanged(int(expected_points), total)
    with transaction.atomic():              # all or nothing: if one payment is refused none is kept
        assets = [start(company, user, e, tier, quote(e, tier, True).total, bundle=True) for e in todo]
    return assets, ''
