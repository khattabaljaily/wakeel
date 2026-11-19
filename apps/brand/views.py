import io
import re
import zipfile

from django.contrib import messages
from django.http import Http404, HttpResponse
from django.shortcuts import get_object_or_404, redirect, render
from django.utils.http import content_disposition_header
from django.utils.translation import gettext as _, gettext_lazy
from django.views.decorators.http import require_POST

from apps.audit import log as audit
from apps.companies.decorators import company_required
from apps.credits.charging import get_wallet
from apps.credits.catalog import format_points
from apps.credits.jobs import expected_points

from . import service
from .models import BrandAsset, BrandFile

NAMES = {
    'logo': gettext_lazy('Logo'), 'logo_variants': gettext_lazy('Logo versions'), 'colors': gettext_lazy('Colour palette'),
    'typography': gettext_lazy('Typography'), 'letterhead': gettext_lazy('Letterhead'), 'business_card': gettext_lazy('Business card'),
    'envelope': gettext_lazy('Envelope'), 'invoice': gettext_lazy('Invoice'), 'receipt': gettext_lazy('Receipt'),
    'file_jacket': gettext_lazy('File jacket'), 'email_signature': gettext_lazy('E-mail signature'),
    'social_kit': gettext_lazy('Social media kit'), 'favicon': gettext_lazy('Favicon and app icons'),
    'pattern': gettext_lazy('Pattern and graphics'), 'deck_template': gettext_lazy('Presentation template'),
    'guidelines': gettext_lazy('Brand guidelines')}
STYLE_NAMES = {'clean': gettext_lazy('Clean'), 'band': gettext_lazy('Colour band'), 'elegant': gettext_lazy('Elegant')}
GROUP_NAMES = {'foundation': gettext_lazy('Foundation'), 'stationery': gettext_lazy('Stationery and documents'),
               'digital': gettext_lazy('Digital'), 'reference': gettext_lazy('Reference')}
NOTES = {
    'logo': (gettext_lazy('One logo concept, drawn for your company.'),
             gettext_lazy('Three different concepts; an art director checks each one by eye and corrects it. You choose.')),
    'default': (gettext_lazy('One design that suits your brand.'), gettext_lazy('Three designs to choose from, with finer details and more formats.')),
}
ICONS = {'logo': 'bi-bezier2', 'logo_variants': 'bi-bezier2', 'colors': 'bi-palette', 'typography': 'bi-fonts', 'letterhead': 'bi-file-earmark-richtext',
         'business_card': 'bi-person-vcard', 'envelope': 'bi-envelope', 'invoice': 'bi-receipt', 'receipt': 'bi-receipt-cutoff', 'file_jacket': 'bi-folder2',
         'email_signature': 'bi-envelope-paper', 'social_kit': 'bi-megaphone', 'favicon': 'bi-app', 'pattern': 'bi-grid-3x3-gap', 'deck_template': 'bi-easel',
         'guidelines': 'bi-journal-richtext'}
PREVIEWS = ('preview-on-white.png', 'c1_preview-on-white.png', 'logo-horizontal.png', 'colors.png', 'typography.png', 'letterhead.png')


_editors = company_required(edit=True)         # owners, administrators and editors build the brand (it spends the company's balance)


def preview_of(asset):
    files = list(asset.files.all())
    by_name = {f.name: f for f in files}
    for name in PREVIEWS:
        if name in by_name:
            return by_name[name]
    return next((f for f in files if f.name.endswith('.png')), None)


@_editors
def studio(request):
    kit = service.get_kit()
    company = request.company
    sections, made = [], 0
    for group in service.GROUPS:
        cards = []
        for key, (g, _en, _ar, _ai) in service.ELEMENTS.items():
            if g != group:
                continue
            done = service.latest(key)
            working = BrandAsset.objects.filter(element=key, status__in=[BrandAsset.QUEUED, BrandAsset.RUNNING]).first()
            made += 1 if done else 0
            cards.append({'key': key, 'icon': ICONS[key], 'name': NAMES[key], 'asset': done, 'preview': preview_of(done) if done else None, 'working': working,
                          'locked': key in service.NEEDS_SYMBOL and not kit.symbol,
                          'prices': [(t, label, service.quote(key, t), n) for (t, label), n in zip(BrandAsset.TIERS, NOTES.get(key, NOTES['default']))],
                          'person': key in service.PERSON_ELEMENTS, 'note': key == 'logo'})
        sections.append((GROUP_NAMES[group], cards))
    palette = [(k, v) for k, v in (kit.palette or {}).items() if v]
    remaining = [e for e in service.ELEMENTS if e != 'logo' and not BrandAsset.objects.filter(element=e, status__in=['done', 'queued', 'running']).exists()]
    kit_logo = {t: service.quote('logo', t, True) for t, _label in BrandAsset.TIERS}          # the logo at the kit's discount: the kit starts with it
    totals = [(t, label, format_points(service.kit_total(t)), kit_logo[t]) for t, label in BrandAsset.TIERS]
    rest = [(t, label, service.quotes.bundle(*[service.quote(e, t, True) for e in remaining])) for t, label in BrandAsset.TIERS] if remaining else []
    return render(request, 'brand/studio.html', {
        'sections': sections, 'kit': kit, 'palette': palette, 'made': made, 'total': len(service.ELEMENTS), 'has_name': bool(company.name),
        'totals': totals, 'rest': rest, 'remaining': len(remaining), 'balance': format_points(get_wallet(company).balance),
        'discount': int(service.KIT_DISCOUNT * 100), 'symbol_data': kit.symbol})


@_editors
@require_POST
def create(request, element):
    if element not in service.ELEMENTS:
        raise Http404
    tier = request.POST.get('tier') if request.POST.get('tier') in dict(BrandAsset.TIERS) else BrandAsset.STANDARD
    if (reason := service.refusal(request.company, element, tier)):
        messages.error(request, reason)
        return redirect('brand:studio')
    person = {k: request.POST.get(k, '').strip()[:120] for k in ('name', 'title', 'phone', 'email')} if element in service.PERSON_ELEMENTS else {}
    asset = service.start(request.company, request.user, element, tier, expected_points(request.POST), person,
                          request.POST.get('note', '') if element == 'logo' else '')
    audit.record(request, 'brand.created', f'{element}:{tier}')
    messages.info(request, _('Working on it. This page shows the result as soon as it is ready.'))
    return redirect('brand:detail', pk=asset.pk)


@_editors
@require_POST
def kit_start(request):
    """Begin a whole kit: the logo now at the kit's discount; after the owner chooses it, 'make the rest' orders everything else."""
    tier = request.POST.get('tier') if request.POST.get('tier') in dict(BrandAsset.TIERS) else BrandAsset.STANDARD
    if (reason := service.refusal(request.company, 'logo', tier)):
        messages.error(request, reason)
        return redirect('brand:studio')
    kit = service.get_kit()
    kit.bundle_tier = tier
    kit.save(update_fields=['bundle_tier'])
    asset = service.start(request.company, request.user, 'logo', tier, expected_points(request.POST), {}, request.POST.get('note', ''), bundle=True)
    audit.record(request, 'brand.kit_started', tier)
    messages.info(request, _('Working on it. This page shows the result as soon as it is ready.'))
    return redirect('brand:detail', pk=asset.pk)


@_editors
@require_POST
def kit_rest(request):
    tier = request.POST.get('tier') if request.POST.get('tier') in dict(BrandAsset.TIERS) else BrandAsset.STANDARD
    assets, reason = service.rest_of_kit(request.company, request.user, tier, expected_points(request.POST))
    if reason:
        messages.error(request, reason)
    else:
        audit.record(request, 'brand.kit_rest', f'{tier}:{len(assets)}')
        messages.info(request, _('The rest of your kit is being designed. Each piece appears in the studio as soon as it is ready.'))
    return redirect('brand:studio')


def _asset(pk):
    return get_object_or_404(BrandAsset, pk=pk)


@_editors
def detail(request, pk):
    asset = _asset(pk)
    files = list(asset.files.all())
    concepts = []
    for c in (asset.design or {}).get('concepts', []):
        n = c['n']
        concepts.append({**c, 'white': next((f for f in files if f.name == f'c{n}_preview-on-white.png'), None),
                         'dark': next((f for f in files if f.name == f'c{n}_preview-on-primary.png'), None)})
    shown = [f for f in files if not re.match(r'^c\d+_', f.name)] if concepts else files
    groups = {}
    for f in shown:        # premium stationery and digital pieces come in three designs: file-<n>-<style>[-page].png / .pdf
        m = re.match(r'^.*-(\d)-(clean|band|elegant)(?:-\d+)?\.(png|pdf)$', f.name)
        if m:
            groups.setdefault((int(m.group(1)), m.group(2)), []).append(f)
    designs = [{'n': n, 'style': STYLE_NAMES[style], 'images': [f for f in fs if f.name.endswith('.png')], 'pdf': next((f for f in fs if f.name.endswith('.pdf')), None)}
               for (n, style), fs in sorted(groups.items())] if len(groups) > 1 else []
    grouped = {f.pk for d in designs for f in d['images'] + ([d['pdf']] if d['pdf'] else [])}
    shown = [f for f in shown if f.pk not in grouped]
    return render(request, 'brand/detail.html', {'a': asset, 'name': NAMES[asset.element], 'files': shown, 'concepts': concepts, 'designs': designs,
                                                  'images': [f for f in shown if f.name.endswith('.png')], 'others': [f for f in shown if not f.name.endswith('.png')]})


@_editors
@require_POST
def choose(request, pk, n):
    asset = _asset(pk)
    if (reason := service.choose_concept(request.company, asset, n)):
        messages.error(request, reason)
        return redirect('brand:detail', pk=pk)
    audit.record(request, 'brand.logo_chosen', asset.design.get('concepts', [{}])[n - 1].get('name', ''))
    messages.success(request, _('This is now your logo. Its colours are your brand colours, and everything you make next is built from it.'))
    return redirect('brand:studio')


CONTENT = {'png': 'image/png', 'svg': 'image/svg+xml', 'pdf': 'application/pdf', 'ico': 'image/x-icon', 'zip': 'application/zip',
           'html': 'text/plain; charset=utf-8', 'txt': 'text/plain; charset=utf-8', 'json': 'application/json', 'css': 'text/plain; charset=utf-8',
           'webmanifest': 'application/manifest+json', 'pptx': 'application/vnd.openxmlformats-officedocument.presentationml.presentation'}


def _attachment(data, name, content_type, inline):
    response = HttpResponse(data, content_type=content_type)
    response['Content-Disposition'] = content_disposition_header(not inline, re.sub(r'[\r\n"]+', ' ', name))
    response['Cache-Control'] = 'private, no-store'
    response['X-Content-Type-Options'] = 'nosniff'
    if content_type == 'image/svg+xml':
        response['Content-Security-Policy'] = "default-src 'none'; style-src 'unsafe-inline'; img-src data:"       # a drawing may draw, never run anything
    return response


@_editors
def file(request, pk, name):
    """One file of a design: shown in the page (images, PDF) or downloaded (?download=1); ?w=480 gives a small PNG for the gallery."""
    f = get_object_or_404(BrandFile, asset_id=pk, name=name)
    with f.file.storage.open(f.file.name, 'rb') as handle:
        data = handle.read()
    ext = name.rsplit('.', 1)[-1].lower()
    width = request.GET.get('w', '')
    if ext == 'png' and width.isdigit() and 64 <= int(width) <= 1600:
        from PIL import Image
        with Image.open(io.BytesIO(data)) as im:
            im.thumbnail((int(width), int(width) * 4))
            out = io.BytesIO()
            im.save(out, 'PNG', optimize=True)
            data = out.getvalue()
    inline = request.GET.get('download') != '1' and ext in ('png', 'svg', 'pdf', 'ico')
    return _attachment(data, name, CONTENT.get(ext, 'application/octet-stream'), inline)


@_editors
def zip_all(request, pk):
    asset = _asset(pk)
    out = io.BytesIO()
    with zipfile.ZipFile(out, 'w', zipfile.ZIP_DEFLATED) as z:
        for f in asset.files.all():
            with f.file.storage.open(f.file.name, 'rb') as handle:
                z.writestr(f.name, handle.read())
    return _attachment(out.getvalue(), f'{NAMES[asset.element]}.zip'.replace('/', ' '), 'application/zip', False)


@_editors
@require_POST
def delete(request, pk):
    asset = _asset(pk)
    for f in asset.files.all():
        f.file.delete(save=False)
    audit.record(request, 'brand.deleted', f'{asset.element}:{asset.tier}')
    asset.delete()
    messages.success(request, _('Deleted.'))
    return redirect('brand:studio')
