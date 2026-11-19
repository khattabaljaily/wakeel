import logging

from django.conf import settings
from django.contrib import messages
from django.core.cache import cache
from django.core.exceptions import ValidationError
from django.core.mail import EmailMessage
from django.core.paginator import Paginator
from django.core.validators import validate_email
from django.db.models import Q
from django.http import Http404, HttpResponse
from django.shortcuts import get_object_or_404, redirect, render
from django.template.loader import render_to_string
from django.urls import reverse
from django.utils.http import url_has_allowed_host_and_scheme
from django.utils import timezone, translation
from django.utils.html import escape
from django.utils.text import slugify
from django.utils.translation import gettext as _
from django.views.decorators.clickjacking import xframe_options_sameorigin
from django.views.decorators.http import require_POST

from apps.audit import log as audit
from apps.audit.models import AuditEvent
from apps.companies.decorators import company_required
from apps.credits.jobs import expected_points
from apps.identity import letterheads
from apps.jobs.models import Job
from apps.library.models import Record
from apps.notifications.services import notify_event, notify_managers_event, who

from . import blanks, generate, jobs, qr, safehtml
from . import pdf as pdf_tools
from .forms import AIDocumentForm, DocumentForm
from .models import Document, DocumentTemplate

logger = logging.getLogger(__name__)
member = company_required
editor = company_required(edit=True)
manager = company_required(manage=True)


@member
def issued(request):
    """The log of the documents issued from the templates: type, date, addressee, who wrote it, status. It never shows
    the text: that is opened one document at a time (Open or Print) and each opening is written to the activity log."""
    documents = Document.objects.select_related('created_by')
    category = request.GET.get('cat', '')
    if category in dict(Record.CATEGORIES):
        documents = documents.filter(category=category)
    else:
        category = ''
    status = request.GET.get('status', '')
    if status in dict(Document.STATUSES):
        documents = documents.filter(status=status)
    else:
        status = ''
    query = (request.GET.get('q') or '').strip()[:100]
    if query:
        documents = documents.filter(Q(title__icontains=query) | Q(doc_type__icontains=query) | Q(recipient__icontains=query))
    page = Paginator(documents, 30).get_page(request.GET.get('page'))
    return render(request, 'documents/issued.html', {
        'page': page, 'cat': category, 'q': query, 'categories': Record.CATEGORIES, 'pdf_available': pdf_tools.available(),
        'status': status, 'statuses': Document.STATUSES})


def _needs_approval(request):
    """True when the company asks for approval and the writer is not who gives it."""
    return request.company.documents_need_approval and not request.membership.can_manage


def _status_for_new(request):
    return Document.DRAFT if _needs_approval(request) else Document.APPROVED


def _blocked_until_approved(request, document):
    """A response when the document is not yet allowed out (printed, downloaded, sent); None when it is."""
    if document.is_approved or not request.company.documents_need_approval:
        return None
    return render(request, 'documents/not_approved.html', {'document': document}, status=403)


def _log_opened(request, doc):
    """Reading the text of an issued document is written to the activity log (who, when, from where)."""
    audit.record(request, AuditEvent.DOC_OPENED, f'Document {doc.pk}', title=doc.title[:100])


def _log_qr(request, doc, before):
    """Putting the verification QR on a document (or taking it off) is written to the activity log."""
    if doc.include_qr != before:
        audit.record(request, AuditEvent.DOC_QR_CHANGED, f'Document {doc.pk}', title=doc.title[:100], qr=doc.include_qr)


# --- Writing a document ---------------------------------------------------------------------------------------------

def _editor(request, document):
    """The form to type or review a document: a new one typed by hand, or any existing one (also what the AI wrote)."""
    before = document.include_qr
    can_add_qr = request.membership.can_manage          # the QR says the company stands behind the paper: owners and admins
    form = DocumentForm(request.POST or None, instance=document)
    if request.method == 'POST' and form.is_valid():
        doc = form.save(commit=False)
        doc.company = request.company
        if not can_add_qr:
            doc.include_qr = before
        if doc.created_by_id is None:
            doc.created_by = request.user
            doc.status = _status_for_new(request)
        elif _needs_approval(request) and doc.status != Document.DRAFT:
            doc.status = Document.DRAFT                    # a member changed an approved text: it must be approved again
        doc.save()
        _log_qr(request, doc, before)
        messages.success(request, _('Saved.'))
        return redirect('documents:edit', pk=doc.pk)
    value_fields = [(i, name, document.values.get(name, '')) for i, name in enumerate(safehtml.blank_names(document.design))] if document.is_designed else []
    quote = jobs.quote_for([generate.FILL_SERVICE if document.is_designed else generate.CONTENT_SERVICE])
    return render(request, 'documents/edit.html', {
        'value_fields': value_fields, 'form': form, 'document': document, 'can_add_qr': can_add_qr,
        'pdf_available': pdf_tools.available(), 'rewrite_quote': quote, 'tools': _insert_tools()})


def _insert_tools():
    """The buttons above the text of a typed document: what each inserts (the line marks drawn by doc_tags)."""
    label, value, item, qty, amount, option = _('Label'), _('Value'), _('Item'), _('Qty'), _('Amount'), _('Option')
    return [(_('Title'), '## '), (_('Section'), '# '), (_('Bullet'), '- '),
            (_('Form table'), f'{label} | {value}\n{label} | {value}'),
            (_('Items table'), f'{item} | {qty} | {amount}\n---\n{item} | 1 | 0.00'),
            (_('Choices'), f'[ ] {option} [ ] {option}'), (_('Note'), '> ')]


def _find_template(doc_type, language):
    return DocumentTemplate.objects.filter(key=DocumentTemplate.make_key(doc_type), language=language).first()


def _ai_new(request, kind):
    """Create a document with the AI: only the request is asked (type, category, language, what it should say). The
    company's template of the type is used when there is one; else the member is asked before one is made. The price of
    each action is shown on its own button and is what is charged (`expected_points_*`)."""
    form = AIDocumentForm(request.POST or None, initial={
        'doc_type': (request.GET.get('type') or '')[:200], 'category': request.GET.get('cat'),
        'language': request.GET.get('lang') or request.LANGUAGE_CODE})
    needs_template = ''
    if request.method == 'POST' and form.is_valid():
        data = form.cleaned_data
        category = data['category'] if data['category'] in dict(Record.CATEGORIES) else Document.DEFAULT_CATEGORY[kind]
        language = data['language'] if data['language'] in dict(settings.LANGUAGES) else request.LANGUAGE_CODE
        doc_type = data['doc_type'].strip()
        template = _find_template(doc_type, language)
        action = request.POST.get('action')
        details = dict(doc_kind=kind, category=category, language=language, doc_type=doc_type, recipient=data['recipient'],
                       instructions=data['instructions'], status=_status_for_new(request))
        if template is not None and action == 'write':
            job = jobs.queue_write(request.company, request.user, expected_points(request.POST.get('expected_points_write') and
                                                                                   {'expected_points': request.POST['expected_points_write']}),
                                   template, False, **details)
            return redirect('documents:working', pk=job.pk)
        if template is None and action == 'write_new_template':
            job = jobs.queue_write(request.company, request.user, expected_points(
                {'expected_points': request.POST.get('expected_points_template')}), None, True, **details)
            return redirect('documents:working', pk=job.pk)
        if template is None:
            needs_template = doc_type          # ask first: making a template is paid
    language = form['language'].value() or request.LANGUAGE_CODE
    write_quote = jobs.quote_for([generate.FILL_SERVICE])
    first_quote = jobs.quote_for([generate.TEMPLATE_SERVICE, generate.FILL_SERVICE])
    return render(request, 'documents/ai_new.html', {
        'form': form, 'kind': kind, 'needs_template': needs_template, 'write_quote': write_quote, 'first_quote': first_quote,
        'template_names': DocumentTemplate.objects.filter(language=language).values_list('name', flat=True)})


@editor
def new(request, kind):
    if kind not in generate.SERVICES:
        return redirect('library:list')
    if request.GET.get('manual') != '1' and request.POST.get('manual') != '1':
        return _ai_new(request, kind)
    category = request.GET.get('cat')
    if category not in dict(Record.CATEGORIES):
        category = Document.DEFAULT_CATEGORY[kind]
    return _editor(request, Document(kind=kind, category=category, language=request.LANGUAGE_CODE))


@editor
def edit(request, pk):
    document = get_object_or_404(Document, pk=pk)
    if request.method == 'GET':
        _log_opened(request, document)
    return _editor(request, document)


@member
def working(request, pk):
    """The page of a paid AI job of this section: it shows the progress and opens the result when the job is done."""
    job = get_object_or_404(Job, pk=pk, company=request.company, kind=Job.Kind.CALL)
    back = request.GET.get('back', '')
    if not (back.startswith('/') and url_has_allowed_host_and_scheme(back, allowed_hosts={request.get_host()})):
        back = reverse('library:list')                 # only a page of this site: never javascript: or another site
    return render(request, 'documents/working.html', {'job': job, 'back': back})


# --- The page of a document: print, PDF, Word, e-mail ---------------------------------------------------------------

def _paper_context(request, document, embed=False, pdf=False, company=None):
    """Everything the page of a document needs. With `pdf` the images and the font are embedded as data URIs, so the
    page can be printed to a file without any request back to the app (and shown to a visitor who is not signed in:
    the verification page passes the document's own `company`)."""
    company = company or request.company
    # The addressee and the date above the text: for letters, and for other documents that have an addressee. A form
    # keeps its own header lines in its text.
    show_meta = document.kind == Document.LETTER or (document.kind == Document.GENERAL and bool(document.recipient))
    letterhead = letterheads.for_document(company, document.language)
    designed = safehtml.render_design(document.design, document.values) if document.is_designed else ''
    context = {'designed_html': designed, 'show_meta': show_meta, 'document': document, 'profile': company,
               'company_name': company.name_for(document.language), 'letterhead': letterhead, 'embed': embed}
    if pdf:
        context['pdf'] = True
        context['font_src'] = pdf_tools.font_uri()
        if letterhead:
            context['letterhead'] = {**letterhead, 'src': pdf_tools.file_uri(letterhead['field'])}
        if company.logo and not letterhead:
            context['logo_src'] = pdf_tools.file_uri(company.logo)
    return context


def _verify_block(request, document, context, log):
    """A document with the verification option carries a code and a QR that open the public verification page."""
    if document.is_verifiable:
        code = document.ensure_code()
        context.update(verify_code=code, qr=qr.svg(request.build_absolute_uri(reverse('verify', args=[code]))))
        if log:
            audit.record(request, AuditEvent.DOC_PRINTED_VERIFIABLE, f'Document {document.pk}', title=document.title[:100])


@xframe_options_sameorigin
@member
def print_view(request, pk):
    """The document on the letterhead. With ?embed=1 it is drawn without the toolbar, for the preview pane."""
    document = get_object_or_404(Document, pk=pk)
    embed = request.GET.get('embed') == '1'
    if not embed and (blocked := _blocked_until_approved(request, document)):
        return blocked
    if not embed and request.GET.get('html') != '1' and pdf_tools.available():
        return redirect(reverse('documents:pdf', args=[document.pk]) + '?inline=1')     # the real pages, with the viewer's Print
    context = _paper_context(request, document, embed)
    context['pdf_available'] = pdf_tools.available()
    if not embed:
        _log_opened(request, document)
    _verify_block(request, document, context, log=not embed)
    with translation.override(document.language):         # a paper speaks its own language, whatever the screen's
        return render(request, 'documents/print.html', context)


def _make_pdf(request, document, preview=False):
    """The document as PDF bytes. Opening the text and printing a document with a QR are written to the activity log
    (a preview, the pane beside the form, is not: it is the same as the form's own text)."""
    context = _paper_context(request, document, pdf=True)
    if not preview:
        _log_opened(request, document)
    _verify_block(request, document, context, log=not preview)
    with translation.override(document.language):
        html = render_to_string('documents/print.html', context, request=request)
    return pdf_tools.html_to_pdf(html)


def _pdf_name(document):
    return (slugify(document.title, allow_unicode=True) or 'document') + '.pdf'


def _cached_pdf(request, key, make):
    """A PDF kept for ten minutes per company (the page is the same until the document or the letterhead changes)."""
    full = f'{key}:{request.company.pk}'
    content = cache.get(full)
    if content is None:
        content = make()
        cache.set(full, content, 600)
    return content


@member
def download_pdf(request, pk):
    """The document as a PDF file to keep or send."""
    document = get_object_or_404(Document, pk=pk)
    if not pdf_tools.available():
        raise Http404
    preview = request.GET.get('preview') == '1'                 # the pane beside the form: shown, not downloaded
    if not preview and (blocked := _blocked_until_approved(request, document)):
        return blocked
    try:
        if preview:
            content = _cached_pdf(request, f'pdf-preview:{document.pk}:{document.updated_at.timestamp()}:{document.status}',
                                  lambda: _make_pdf(request, document, preview=True))
        else:
            content = _make_pdf(request, document)
    except pdf_tools.PdfError:
        if preview:
            raise Http404
        messages.error(request, _('The PDF could not be made. Use Preview and print instead.'))
        return redirect('documents:edit', pk=document.pk) if request.membership.can_edit else redirect('documents:issued')
    response = HttpResponse(content, content_type='application/pdf')
    response['Content-Disposition'] = f'{"inline" if preview or request.GET.get("inline") == "1" else "attachment"}; filename="{_pdf_name(document)}"'
    response['X-Frame-Options'] = 'SAMEORIGIN'
    response['Cache-Control'] = 'private, no-store'
    return response


def _docx_bytes(request, document):
    """The document as a Word file to edit: the same page as the PDF (a designed page with its CSS, or the text of the document),
    without the letterhead, which the company's own Word template carries. Opening it is written to the activity log
    like a print."""
    from . import docx_export
    from .templatetags import doc_tags
    with translation.override(document.language):
        if document.is_designed:
            html = safehtml.render_design(document.design, document.values)
        else:
            html = ''
            if document.kind == Document.LETTER or (document.kind == Document.GENERAL and document.recipient):
                html += f'<p dir="auto">{escape(document.addressed_to)}</p><p dir="ltr">{document.doc_date:%Y-%m-%d}</p>' if document.doc_date else f'<p dir="auto">{escape(document.addressed_to)}</p>'
            if document.subject and not doc_tags.has_title(document.body):
                prefix = (_('Subject:') + ' ') if document.kind == Document.LETTER else ''
                html += f'<h2 dir="auto">{escape(prefix + document.subject)}</h2>'
            html += str(doc_tags.document_body(document.body))
            if document.kind == Document.CERTIFICATE and document.doc_date:
                html += f'<p dir="ltr">{document.doc_date:%Y-%m-%d}</p>'
        if document.is_verifiable:
            code = document.ensure_code()
            html += '<p>' + escape(_('Verify this document')) + f': <span dir="ltr">{escape(request.build_absolute_uri(reverse("verify", args=[code])))}</span></p>'
    _log_opened(request, document)
    _verify_block(request, document, {}, log=True)
    return docx_export.build(html, rtl=document.language in ('ar', 'fa'), title=document.title)


@member
def download_docx(request, pk):
    """The document as a Word file."""
    document = get_object_or_404(Document, pk=pk)
    if blocked := _blocked_until_approved(request, document):
        return blocked
    response = HttpResponse(_docx_bytes(request, document),
                            content_type='application/vnd.openxmlformats-officedocument.wordprocessingml.document')
    response['Content-Disposition'] = f'attachment; filename="{_pdf_name(document)[:-4]}.docx"'
    response['Cache-Control'] = 'private, no-store'
    return response


@member
def download_docx(request, pk):
    """The document as a Word file."""
    document = get_object_or_404(Document, pk=pk)
    if blocked := _blocked_until_approved(request, document):
        return blocked
    response = HttpResponse(_docx_bytes(request, document),
                            content_type='application/vnd.openxmlformats-officedocument.wordprocessingml.document')
    response['Content-Disposition'] = f'attachment; filename="{_pdf_name(document)[:-4]}.docx"'
    response['Cache-Control'] = 'private, no-store'
    return response


EMAILS_PER_HOUR = 10


@editor
@require_POST
def email_document(request, pk):
    """Send the document as a PDF to an address (the member's choice), with a short message. Logged in the activity log."""
    document = get_object_or_404(Document, pk=pk)
    if blocked := _blocked_until_approved(request, document):
        return blocked
    to = (request.POST.get('to') or '').strip()
    note = (request.POST.get('message') or '').strip()[:1000]
    try:
        validate_email(to)
    except ValidationError:
        messages.error(request, _('Enter a valid e-mail address.'))
        return redirect('documents:edit', pk=document.pk)
    if not pdf_tools.available():
        raise Http404
    key = f'doc-mail:{request.user.pk}'
    cache.add(key, 0, 3600)
    if cache.incr(key) > EMAILS_PER_HOUR:
        messages.error(request, _('You have sent many documents in the last hour. Try again later.'))
        return redirect('documents:edit', pk=document.pk)
    try:
        content = _make_pdf(request, document)
    except pdf_tools.PdfError:
        messages.error(request, _('The PDF could not be made. Use Preview and print instead.'))
        return redirect('documents:edit', pk=document.pk)
    company = request.company.name_for(document.language)
    with translation.override(document.language):
        subject = _('%(company)s: %(title)s') % {'company': company, 'title': document.title}
        body = (note + '\n\n' if note else '') + _('The document is attached as a PDF file.') + f'\n\n{company}'
    mail = EmailMessage(subject, body, to=[to], reply_to=[request.user.email])
    mail.attach(_pdf_name(document), content, 'application/pdf')
    try:
        mail.send()
    except Exception:
        logger.warning('Could not e-mail document %s', document.pk, exc_info=True)
        messages.error(request, _('The e-mail could not be sent. Try again later.'))
        return redirect('documents:edit', pk=document.pk)
    audit.record(request, AuditEvent.DOC_EMAILED, f'Document {document.pk}', title=document.title[:100], to=to)
    messages.success(request, _('The document was sent to %(to)s.') % {'to': to})
    return redirect('documents:edit', pk=document.pk)


@editor
@require_POST
def delete(request, pk):
    get_object_or_404(Document, pk=pk).delete()
    messages.success(request, _('Deleted.'))
    return redirect('documents:issued')


@manager
@require_POST
def revoke(request, pk):
    """Cancel a document that was issued (the owner or an admin), or reinstate it. The QR keeps working but says so."""
    document = get_object_or_404(Document, pk=pk)
    if request.POST.get('undo'):
        document.revoked_at = None
        event, message = AuditEvent.DOC_REINSTATED, _('The document is valid again.')
    else:
        document.revoked_at = document.revoked_at or timezone.now()
        event, message = AuditEvent.DOC_REVOKED, _('The document was cancelled. Its verification page now says so.')
    document.save(update_fields=['revoked_at'])
    audit.record(request, event, f'Document {document.pk}', title=document.title[:100])
    messages.success(request, message)
    return redirect('documents:edit', pk=document.pk)


# --- Revising a written document (paid), the blanks of a designed one ----------------------------------------------------

@editor
@require_POST
def rewrite(request, pk):
    """Ask the AI to revise the saved text as told (the writing price, shown on the button and charged as shown)."""
    document = get_object_or_404(Document, pk=pk)
    notes = (request.POST.get('notes') or '').strip()
    if not notes:
        messages.error(request, _('Tell the AI what should change.'))
        return redirect('documents:edit', pk=document.pk)
    job = jobs.queue_rewrite(request.company, request.user, expected_points(request.POST), document, notes)
    return redirect('documents:working', pk=job.pk)


@editor
@require_POST
def values(request, pk):
    """Save the values of the blanks of a designed document (the page is made again from them)."""
    document = get_object_or_404(Document, pk=pk)
    if document.is_designed:
        names = safehtml.blank_names(document.design)
        document.values = {name: (request.POST.get(f'v-{i}') or '').strip()[:blanks.MAX_VALUE] for i, name in enumerate(names)}
        if _needs_approval(request) and document.status != Document.DRAFT:
            document.status = Document.DRAFT
        document.save()
        messages.success(request, _('Saved.'))
    return redirect('documents:edit', pk=document.pk)


# --- Approval -------------------------------------------------------------------------------------------------------

@editor
@require_POST
def submit(request, pk):
    """The writer sends a draft to the owner or an administrator for approval."""
    document = get_object_or_404(Document, pk=pk)
    if document.status in (Document.DRAFT, Document.REJECTED):
        document.status = Document.PENDING
        document.save(update_fields=['status'])
        audit.record(request, AuditEvent.DOC_SUBMITTED, f'Document {document.pk}', title=document.title[:100])
        # In the notification centre and by e-mail; the text of the document is never in either.
        notify_managers_event(request.company, 'document_pending', exclude=request.user, email=True,
                              url=reverse('documents:edit', args=[document.pk]), who=who(request.user), title=document.title)
        messages.success(request, _('The document was sent for approval.'))
    return redirect('documents:edit', pk=document.pk)


@manager
@require_POST
def review(request, pk):
    """The owner or an administrator approves or rejects a document that waits for approval."""
    document = get_object_or_404(Document, pk=pk)
    decision = request.POST.get('decision')
    if document.status == Document.PENDING and decision in ('approve', 'reject'):
        approved = decision == 'approve'
        document.status = Document.APPROVED if approved else Document.REJECTED
        document.reviewed_by, document.reviewed_at = request.user, timezone.now()
        document.review_note = (request.POST.get('note') or '').strip()[:300]
        document.save(update_fields=['status', 'reviewed_by', 'reviewed_at', 'review_note'])
        audit.record(request, AuditEvent.DOC_APPROVED if approved else AuditEvent.DOC_REJECTED,
                     f'Document {document.pk}', title=document.title[:100], note=document.review_note)
        if document.created_by_id and document.created_by_id != request.user.pk:
            notify_event(document.created_by, 'document_approved' if approved else 'document_rejected', company=request.company,
                         url=reverse('documents:edit', args=[document.pk]), title=document.title)
        messages.success(request, _('The document was approved.') if approved else _('The document was rejected.'))
    return redirect('documents:edit', pk=document.pk)


# --- Templates --------------------------------------------------------------------------------------------------------

@member
def template_list(request):
    return render(request, 'documents/templates.html', {
        'templates': DocumentTemplate.objects.all(), 'write_quote': jobs.quote_for([generate.FILL_SERVICE]),
        'design_quote': jobs.quote_for([generate.TEMPLATE_SERVICE])})


@editor
@require_POST
def template_save(request, pk):
    """Keep a document as a template. The stamp and the signature are not kept."""
    document = get_object_or_404(Document, pk=pk)
    name = (request.POST.get('name') or '').strip()[:200] or document.title
    if DocumentTemplate.objects.filter(key=DocumentTemplate.make_key(name), language=document.language).exists():
        messages.error(request, _('You already have a template of this type. Choose another name, or redesign the existing one.'))
        return redirect('documents:edit', pk=document.pk)
    DocumentTemplate.objects.create(
        company=request.company, kind=document.kind, name=name, recipient=document.recipient, subject=document.subject,
        body=document.body, category=document.category, language=document.language, created_by=request.user)
    messages.success(request, _('Saved as a template. Write {{like this}} for a blank to fill each time.'))
    return redirect('documents:templates')


@editor
def template_use(request, pk):
    """Ask for each blank of the template, then make a new document from it (free: no AI)."""
    template = get_object_or_404(DocumentTemplate, pk=pk)
    names = safehtml.blank_names(template.html) if template.is_designed else blanks.blanks(template.recipient, template.subject, template.body)
    values = {}
    if request.method == 'POST':
        values = {name: (request.POST.get(f'blank-{i}') or '').strip()[:blanks.MAX_VALUE] for i, name in enumerate(names)}
        if template.is_designed:                       # a designed page may keep blanks empty: they print as dotted lines
            document = Document.objects.create(
                company=request.company, kind=template.kind, title=template.name, doc_type=template.name, category=template.category,
                language=template.language, created_by=request.user, status=_status_for_new(request))
            document.design, document.values, document.subject = template.html, values, template.subject
            document.save()
            messages.success(request, _('Document created from the template.'))
            return redirect('documents:edit', pk=document.pk)
        if all(values.values()):
            document = Document.objects.create(
                company=request.company, kind=template.kind, title=template.name, language=template.language,
                category=template.category, recipient=blanks.fill(template.recipient, values), created_by=request.user,
                status=_status_for_new(request))
            document.subject, document.body = blanks.fill(template.subject, values), blanks.fill(template.body, values)
            document.save()
            messages.success(request, _('Document created from the template.'))
            return redirect('documents:edit', pk=document.pk)
        messages.error(request, _('Fill in every blank.'))
    return render(request, 'documents/template_use.html', {
        'template': template, 'fields': [(i, name, values.get(name, '')) for i, name in enumerate(names)]})


@editor
@require_POST
def template_delete(request, pk):
    get_object_or_404(DocumentTemplate, pk=pk).delete()
    messages.success(request, _('Deleted.'))
    return redirect('documents:templates')


@editor
@require_POST
def template_redesign(request, pk):
    """Make the template again (what to change may be told): the design price is charged as shown, and the documents
    already written from the old one are left as they are."""
    template = get_object_or_404(DocumentTemplate, pk=pk)
    job = jobs.queue_redesign(request.company, request.user, expected_points(request.POST), template,
                              (request.POST.get('notes') or '').strip())
    return redirect('documents:working', pk=job.pk)


@editor
@require_POST
def template_import(request, pk):
    """Make a template from an uploaded paper: free for the customer (the platform pays, a few a day)."""
    record = get_object_or_404(Record, pk=pk)
    if jobs.imports_left(request.company) <= 0:
        messages.error(request, _('You have imported the free templates allowed for today. Try again tomorrow.'))
        return redirect(f"{reverse('library:list')}?rec={record.pk}")
    job = jobs.queue_import(request.company, request.user, record)
    return redirect('documents:working', pk=job.pk)


def _template_document(request, template):
    document = Document(kind=template.kind, language=template.language, title=template.name, category=template.category,
                        company=request.company)
    document.subject, document.body = template.subject, template.body
    return document


@member
def template_pdf(request, pk):
    """A template as the PDF it would print as (blanks highlighted): the real pages, for the pane in the library."""
    template = get_object_or_404(DocumentTemplate, pk=pk)
    if not pdf_tools.available():
        raise Http404
    document = _template_document(request, template)

    def make():
        context = _paper_context(request, document, pdf=True)
        context.update(template_mode=True, show_meta=template.kind == Document.LETTER,
                       designed_html=safehtml.render_design(template.html, marks=True) if template.is_designed else '')
        with translation.override(template.language):
            return pdf_tools.html_to_pdf(render_to_string('documents/print.html', context, request=request))
    key = f'pdf-template:{template.pk}:{hash((template.subject, template.body, template.html, template.language))}'
    try:
        content = _cached_pdf(request, key, make)
    except pdf_tools.PdfError:
        raise Http404
    response = HttpResponse(content, content_type='application/pdf')
    response['Content-Disposition'] = 'inline; filename="template.pdf"'
    response['X-Frame-Options'] = 'SAMEORIGIN'
    response['Cache-Control'] = 'private, no-store'
    return response


@xframe_options_sameorigin
@member
def template_preview(request, pk):
    """A template drawn as a document on the company's letterhead, its blanks highlighted: what every document of the
    type will look like. No codes: it is not a document."""
    template = get_object_or_404(DocumentTemplate, pk=pk)
    document = _template_document(request, template)
    company = request.company
    with translation.override(template.language):
        return render(request, 'documents/print.html', {
            'document': document, 'profile': company, 'company_name': company.name_for(template.language),
            'letterhead': letterheads.for_document(company, template.language), 'embed': True, 'template_mode': True,
            'show_meta': template.kind == Document.LETTER,
            'designed_html': safehtml.render_design(template.html, marks=True) if template.is_designed else ''})
