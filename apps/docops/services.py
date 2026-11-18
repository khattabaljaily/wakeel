"""«Services» in the main menu: the AI operations as services of their own. Choose one, upload a file (kept in the
library, encrypted, under «Other documents») or pick a document already there, see the pages and the price, run it.
The run itself is the same as from a document's page (views.run)."""
from django.contrib import messages
from django.shortcuts import get_object_or_404, redirect, render
from django.utils.translation import gettext as _

from apps.credits import quote as quotes
from apps.library.forms import MAX_BYTES, sniff
from apps.library.models import Record

from . import ops
from .models import Operation
from .views import _editor, _member

KINDS = (Operation.TRANSLATE, Operation.SUMMARIZE, Operation.EXTRACT, Operation.WORD, Operation.OCR)


@_member
def hub(request):
    cards = [(kind, quotes.make(ops.SERVICES[kind], pages=1).usd) for kind in KINDS]
    recent = Operation.objects.select_related('record')[:10]
    return render(request, 'docops/services/hub.html', {'cards': cards, 'recent': recent,
                                                        })


@_editor
def start(request, kind):
    if kind not in KINDS:
        return redirect('services:hub')
    error = ''
    if request.method == 'POST':
        upload = request.FILES.get('file')
        if upload:
            content_type = sniff(upload) if upload.size <= MAX_BYTES else None
            if upload.size > MAX_BYTES:
                error = _('The file must be smaller than 10 MB.')
            elif content_type is None:
                error = _('The file must be a PDF, PNG, JPG or WebP.')
            else:
                record = Record(company=request.company, category=Record.OTHER, content_type=content_type, size=upload.size,
                                uploaded_by=request.user,
                                title=(upload.name or '').rsplit('.', 1)[0][:200] or _('Untitled document'))
                record.file.save(upload.name, upload, save=False)
                record.save()
                return redirect('services:confirm', kind=kind, pk=record.pk)
        elif request.POST.get('record', '').isdigit():
            record = get_object_or_404(Record, pk=int(request.POST['record']))
            return redirect('services:confirm', kind=kind, pk=record.pk)
        else:
            error = _('Upload a file or choose a document.')
    documents = Record.objects.order_by('-created_at')[:100]
    return render(request, 'docops/services/start.html', {'kind': kind, 'documents': documents, 'error': error,
                                                          'price_one': quotes.make(ops.SERVICES[kind], pages=1).usd})


@_editor
def confirm(request, kind, pk):
    if kind not in KINDS:
        return redirect('services:hub')
    record = get_object_or_404(Record, pk=pk)
    pages = ops.page_count(record)
    if pages is None:
        messages.error(request, _('This file could not be read. You were not charged.'))
        return redirect('services:start', kind=kind)
    from django.conf import settings
    from django.utils import translation
    from enjaz_docai import pricing
    current = translation.get_language() or 'en'
    current = current if current in dict(settings.LANGUAGES) else 'en'
    return render(request, 'docops/services/confirm.html', {
        'kind': kind, 'record': record, 'pages': pages, 'pages_total': ops.total_pages(record),
        'max_pages': ops.MAX_PAGES,
        'languages': [(code, name, pricing.language_script(code)) for code, name in settings.LANGUAGES],
        'current_language': current, 'lengths': Operation.LENGTHS,
        'options': ops.option_prices(kind, record, pages, current if kind == 'translate' else '')})
