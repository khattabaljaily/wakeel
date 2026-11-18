import re

from django.contrib import messages
from django.http import Http404, HttpResponse
from django.shortcuts import get_object_or_404, redirect, render
from django.utils import translation
from django.utils.http import content_disposition_header
from django.utils.translation import gettext as _
from django.views.decorators.http import require_POST

from apps.audit import log as audit
from apps.companies.decorators import company_required
from apps.credits.catalog import format_points
from apps.credits.charging import get_wallet
from apps.credits.jobs import expected_points

from . import service
from .forms import PresentationForm
from .models import Presentation

PPTX = 'application/vnd.openxmlformats-officedocument.presentationml.presentation'
_editors = company_required(edit=True)       # viewers cannot make presentations: they spend the company's balance


def _language():
    code = translation.get_language() or 'en'
    return code if code in dict(Presentation._meta.get_field('language').choices) else 'en'


@_editors
def presentation_list(request, form=None, open_form=False):
    return render(request, 'presentations/list.html', {
        'items': Presentation.objects.all(), 'form': form or PresentationForm(language=_language()), 'open_form': open_form,
        'tiers': [(t, label, q, note) for t, label, q, note in service.tier_prices(10)]})


@_editors
def new(request):
    """Two steps: the request is checked and its exact price shown (nothing is charged), then confirmed and run."""
    form = PresentationForm(request.POST or None, language=_language())
    if request.method != 'POST' or not form.is_valid():
        return presentation_list(request, form, open_form=True)
    made = form.save(commit=False)
    made.source = form.cleaned_data.get('source_record')
    pages = service.source_pages_of(made.source)
    if not made.title.strip():
        made.title = (made.brief.strip() or (made.source.title if made.source else ''))[:60] or _('Presentation')
    reason = service.refusal(request.company, request.user, made.tier, made.slides, pages)
    quote = service.quote(made.tier, made.slides, pages)
    if request.POST.get('confirm') and not reason:
        # Charged here at the price that was shown (expected_points); a refused payment is answered by the payment middleware.
        made = service.start(request.company, request.user, made, expected_points(request.POST))
        audit.record(request, 'presentation.created', made.title)
        messages.info(request, _('Working on it. This page shows the result as soon as it is ready.'))
        return redirect('presentations:detail', pk=made.pk)
    if reason:
        messages.error(request, reason)
    return render(request, 'presentations/confirm.html', {
        'p': made, 'quote': quote, 'balance': format_points(get_wallet(request.company).balance), 'source': made.source,
        'source_pages': pages, 'blocked': bool(reason),
        'fields': [(f.name, form[f.name].value()) for f in form if form[f.name].value() not in (None, '')]})


@_editors
def detail(request, pk):
    p = get_object_or_404(Presentation, pk=pk)
    return render(request, 'presentations/detail.html', {'p': p, 'outline': p.outline})


def _attachment(data, name, content_type, inline=False):
    response = HttpResponse(data, content_type=content_type)
    response['Content-Disposition'] = content_disposition_header(not inline, re.sub(r'[\r\n"]+', ' ', name))
    response['Cache-Control'] = 'private, no-store'
    response['X-Content-Type-Options'] = 'nosniff'
    return response


@_editors
def file(request, pk, kind):
    """The PowerPoint (download) or its PDF preview (shown in the page)."""
    p = get_object_or_404(Presentation, pk=pk)
    if p.status != Presentation.DONE or kind not in ('pptx', 'preview'):
        raise Http404
    field = p.pptx if kind == 'pptx' else p.preview
    with field.storage.open(field.name, 'rb') as handle:
        data = handle.read()
    name = re.sub(r'[\\/:*?"<>|]+', ' ', p.title).strip() or 'presentation'
    if kind == 'pptx':
        return _attachment(data, f'{name}.pptx', PPTX)
    response = _attachment(data, f'{name}.pdf', 'application/pdf', inline=True)
    response['X-Frame-Options'] = 'SAMEORIGIN'
    return response


@_editors
@require_POST
def delete(request, pk):
    p = get_object_or_404(Presentation, pk=pk)
    title = p.title
    for field in (p.pptx, p.preview):
        if field:
            field.delete(save=False)
    p.delete()
    audit.record(request, 'presentation.deleted', title)
    messages.success(request, _('Deleted.'))
    return redirect('presentations:list')
