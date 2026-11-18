"""Letterheads by language. The one in the company's main language lives on the company; the others are LetterheadVariant
rows. A document is printed on the letterhead of its own language, and on the main one when there is none for that language."""
from django.conf import settings
from django.contrib import messages
from django.http import FileResponse, Http404
from django.shortcuts import redirect, render
from django.urls import reverse
from django.utils.translation import gettext as _
from django.views.decorators.http import require_POST

from apps.companies.decorators import company_required

from . import ai, safearea
from .forms import LetterheadUploadForm
from .models import LetterheadVariant

CSP = "default-src 'none'; style-src 'unsafe-inline'; sandbox"


def for_document(company, language):
    """The letterhead to print a document written in `language` on: {'url', 'exact', 'language', 'top', 'bottom', 'field'}
    (the margins, in mm, between which the text goes) or None."""
    if language != company.main_language:
        variant = LetterheadVariant.objects.for_company(company).filter(language=language).first()
        if variant:
            top, bottom = safearea.margins(variant.file)
            return {'url': reverse('identity:letterhead_file', args=[language]), 'exact': True, 'language': language,
                    'top': top, 'bottom': bottom, 'field': variant.file}
    if company.letterhead:
        top, bottom = safearea.margins(company.letterhead)
        return {'url': reverse('identity:letterhead_main'), 'exact': language == company.main_language,
                'language': company.main_language, 'top': top, 'bottom': bottom, 'field': company.letterhead}
    return None


def rows(company):
    """Every letterhead of the company, the main-language one first."""
    out = []
    if company.letterhead:
        out.append({'language': company.main_language, 'main': True, 'source': company.asset_sources.get('letterhead', ''),
                    'url': reverse('identity:letterhead_main')})
    for variant in LetterheadVariant.objects.for_company(company):
        out.append({'language': variant.language, 'main': False, 'source': variant.source,
                    'url': reverse('identity:letterhead_file', args=[variant.language])})
    names = dict(settings.LANGUAGES)
    for row in out:
        row['name'] = names.get(row['language'], row['language'])
    return out


def save(company, language, content, name, source):
    """Store `content` as the letterhead of `language`, replacing the one it had."""
    if language == company.main_language:
        if company.letterhead:
            company.letterhead.delete(save=False)
        company.letterhead.save(name, content, save=False)
        company.asset_sources = {**company.asset_sources, 'letterhead': source}
        company.save(update_fields=['letterhead', 'asset_sources'])
        return
    variant = LetterheadVariant.objects.for_company(company).filter(language=language).first()
    if variant is None:
        variant = LetterheadVariant(company=company, language=language)
    elif variant.file:
        variant.file.delete(save=False)
    variant.source = source
    variant.file.save(name, content, save=False)
    variant.save()


def _file_response(field):
    response = FileResponse(field.open('rb'))
    response['Cache-Control'] = 'private, no-store'
    response['X-Content-Type-Options'] = 'nosniff'
    response['Content-Security-Policy'] = CSP     # a created letterhead may be SVG: it may draw, never run anything
    return response


@company_required
def page(request):
    """The letterheads of the company: every member sees them, owners and administrators change them."""
    company = request.company
    from apps.credits import quote as quotes
    return render(request, 'identity/letterheads.html', {
        'create_quote': quotes.make(ai.LETTERHEAD_SERVICE), 'rows': rows(company), 'languages': settings.LANGUAGES, 'can_manage': request.membership.can_manage,
        'main_name': dict(settings.LANGUAGES).get(company.main_language, company.main_language)})


@company_required(manage=True)
@require_POST
def add(request):
    form = LetterheadUploadForm(request.POST, request.FILES)
    if not form.is_valid():
        for errors in form.errors.values():
            for error in errors:
                messages.error(request, error)
        return redirect('identity:letterheads')
    upload = form.cleaned_data['file']
    save(request.company, form.cleaned_data['language'], upload, getattr(upload, 'name', 'letterhead.png'), 'uploaded')
    messages.success(request, _('The letterhead is saved.'))
    return redirect('identity:letterheads')


@company_required(manage=True)
@require_POST
def create(request):
    """The AI creates a letterhead in a language (a paid job, charged at the price shown)."""
    from apps.credits.jobs import expected_points
    language = request.POST.get('language', '')
    if language not in dict(settings.LANGUAGES):
        messages.error(request, _('Choose a language.'))
        return redirect('identity:letterheads')
    job = ai.queue_letterhead(request.company, request.user, expected_points(request.POST), language, request.POST.get('note', ''))
    return redirect('documents:working', pk=job.pk)


@company_required(manage=True)
@require_POST
def detect(request):
    """Read the company's details from a paper it has (a paid job). Answers with the job to wait for: its result fills the form."""
    from django.http import JsonResponse

    from apps.credits.jobs import expected_points
    upload = request.FILES.get('paper')
    if upload is None:
        return JsonResponse({'error': _('Choose a file first.')}, status=400)
    try:
        block = ai.prepare_paper(upload)
    except ValueError as exc:
        return JsonResponse({'error': str(exc)}, status=400)
    job = ai.queue_detect(request.company, request.user, expected_points(request.POST), block)
    return JsonResponse({'job': job.pk})


@company_required(manage=True)
@require_POST
def delete(request, language):
    company = request.company
    if language == company.main_language and company.letterhead:
        company.letterhead.delete(save=False)
        company.asset_sources = {k: v for k, v in company.asset_sources.items() if k != 'letterhead'}
        company.save(update_fields=['letterhead', 'asset_sources'])
    else:
        variant = LetterheadVariant.objects.for_company(company).filter(language=language).first()
        if variant is None:
            raise Http404
        variant.delete()
    messages.success(request, _('Deleted.'))
    return redirect('identity:letterheads')


@company_required
def file(request, language):
    """The letterhead of one language, for members of the company only."""
    variant = LetterheadVariant.objects.for_company(request.company).filter(language=language).first()
    if variant is None or not variant.file:
        raise Http404
    return _file_response(variant.file)


@company_required
def main_file(request):
    """The letterhead in the company's main language."""
    if not request.company.letterhead:
        raise Http404
    return _file_response(request.company.letterhead)
