import logging
import re

from django.contrib import messages
from django.http import Http404, HttpResponse
from django.utils.http import content_disposition_header, url_has_allowed_host_and_scheme
from django.urls import reverse
from django.shortcuts import get_object_or_404, redirect, render
from django.utils import translation
from django.utils.translation import gettext as _
from django.views.decorators.http import require_POST

from apps.companies.decorators import company_required
from apps.credits.jobs import expected_points
from apps.library.models import Record

from . import ops
from .models import RTL_LANGUAGES, Operation

logger = logging.getLogger(__name__)
DOCX = 'application/vnd.openxmlformats-officedocument.wordprocessingml.document'


_member = company_required
_editor = company_required(edit=True)         # viewers read results; the others run operations (they spend the company's balance)


@_editor
@require_POST
def run(request, pk, kind):
    record = get_object_or_404(Record, pk=pk)
    # Charged here at the price that was shown (expected_points); a refused payment is answered by the payment middleware.
    operation, message = ops.start(request.company, request.user, record, kind, request.POST.get('tier') or Operation.STANDARD,
                                   request.POST.get('language', ''), request.POST.get('length', ''),
                                   request.POST.get('source_language', ''), expected_points(request.POST))
    if operation is None:
        messages.error(request, message)
        back = request.POST.get('back', '')
        if back and url_has_allowed_host_and_scheme(back, allowed_hosts={request.get_host()}):
            return redirect(back)                     # the services page it was started from
        return redirect(f"{reverse('library:list')}?rec={record.pk}")
    messages.info(request, message)
    return redirect('docops:result', pk=operation.pk)


@_member
def result(request, pk):
    operation = get_object_or_404(Operation.objects.select_related('record'), pk=pk)
    sections = [(key, label, operation.data.get(key, [])) for key, label in (
        ('parties', _('Parties')), ('dates', _('Dates')), ('amounts', _('Amounts')),
        ('obligations', _('Duties and conditions')), ('references', _('Reference numbers')))]
    return render(request, 'docops/result.html', {'op': operation, 'record': operation.record, 'sections': sections,
                                                  'formats': formats_of(operation)})


@_editor
@require_POST
def delete(request, pk):
    operation = get_object_or_404(Operation, pk=pk)
    record_pk = operation.record_id
    operation.delete()
    messages.success(request, _('Deleted.'))
    return redirect(f"{reverse('library:list')}?rec={record_pk}")


def _attachment(data, name, content_type):
    response = HttpResponse(data, content_type=content_type)
    response['Content-Disposition'] = content_disposition_header(True, re.sub(r'[\r\n"]+', ' ', name))
    response['Cache-Control'] = 'private, no-store'
    response['X-Content-Type-Options'] = 'nosniff'
    return response


# What each option delivers: the downloads are part of what was paid for, nothing more.
FORMATS = {
    (Operation.TRANSLATE, Operation.STANDARD): ('docx', 'txt'), (Operation.TRANSLATE, Operation.FORMATTED): ('pdf', 'docx', 'txt'),
    (Operation.TRANSLATE, Operation.PREMIUM): ('file', 'designed-docx'),
    (Operation.SUMMARIZE, Operation.STANDARD): ('docx', 'txt'), (Operation.SUMMARIZE, Operation.FORMATTED): ('pdf', 'docx', 'txt'),
    (Operation.SUMMARIZE, Operation.PREMIUM): ('designed-pdf', 'designed-docx'),
    (Operation.WORD, Operation.STANDARD): ('file',), (Operation.WORD, Operation.PREMIUM): ('file',),
    (Operation.OCR, Operation.STANDARD): ('txt', 'docx', 'pdf'),
}


def formats_of(operation):
    return FORMATS.get((operation.kind, operation.tier), ()) if operation.status == Operation.DONE else ()


@_member
def download(request, pk, fmt):
    """A result as a file, in the formats its option delivers (FORMATS)."""
    from enjaz_docai import design_docx, render, summarize, textdoc_docx
    operation = get_object_or_404(Operation.objects.select_related('record'), pk=pk)
    if fmt not in formats_of(operation):
        raise Http404
    record = operation.record
    base = ops._file_name(record)
    name = base if operation.kind == Operation.WORD else f'{base} - {operation.get_kind_display()}'
    if fmt == 'file':
        ext = 'pdf' if operation.file.name.endswith('.pdf') else 'docx'
        with operation.file.storage.open(operation.file.name, 'rb') as handle:
            return _attachment(handle.read(), f'{name}.{ext}', 'application/pdf' if ext == 'pdf' else DOCX)
    rtl = operation.language in RTL_LANGUAGES or (operation.kind == Operation.OCR and ops.is_rtl_text(operation.text))
    language = operation.language or ('ar' if rtl else 'en')
    markdown = operation.kind == Operation.SUMMARIZE and operation.tier != Operation.STANDARD
    text = summarize.summary_markup(operation.text) if markdown else operation.text
    with translation.override(language):
        title = f'{record.title} — {operation.get_kind_display()}'
        try:
            if fmt == 'txt':
                return _attachment(text.encode('utf-8'), f'{name}.txt', 'text/plain; charset=utf-8')
            if fmt == 'docx':
                return _attachment(textdoc_docx.build_docx(text, rtl), f'{name}.docx', DOCX)
            if fmt == 'pdf':
                if markdown:
                    pdf = summarize.formatted_pdf(operation.text, language, title=record.title, subtitle=operation.get_kind_display(),
                                                  brand='Wakeel', accent='#6d5ef8')
                else:
                    pdf = render.text_pdf(text, language, title)
                return _attachment(pdf, f'{name}.pdf', 'application/pdf')
            if operation.kind == Operation.TRANSLATE:                       # designed-docx of a premium translation
                return _attachment(design_docx.build(operation.data['design']), f'{name}.docx', DOCX)
            design = summarize.premium_design(
                operation.text, language, title=record.title, date=operation.created_at.strftime('%Y-%m-%d'),
                eyebrow=f"{_('Summary')} · Wakeel",
                footer=_('Written by AI from the uploaded file. Check it before you rely on it.'))
            if fmt == 'designed-pdf':
                return _attachment(summarize.premium_pdf(design), f'{name}.pdf', 'application/pdf')
            return _attachment(summarize.word(operation.text, language, design), f'{name}.docx', DOCX)
        except Exception:
            logger.exception('Could not make the %s file of result %s', fmt, operation.pk)
            messages.error(request, _('The file could not be made. Please try again.'))
            return redirect('docops:result', pk=operation.pk)
