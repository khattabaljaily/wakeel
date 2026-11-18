from django.contrib import messages
from django.db.models import Q
from django.http import FileResponse
from django.shortcuts import get_object_or_404, redirect, render
from django.urls import reverse
from django.utils.text import slugify
from django.utils.translation import gettext as _
from django.views.decorators.clickjacking import xframe_options_sameorigin
from django.views.decorators.http import require_POST

from apps.audit import log as audit
from apps.audit.models import AuditEvent
from apps.companies.decorators import company_required
from apps.documents import jobs as document_jobs
from apps.documents import pdf as pdf_tools
from apps.documents.models import DocumentTemplate
from apps.jobs.models import Job

from apps.credits import quote as quotes
from apps.credits.jobs import expected_points
from . import extract, folders
from .forms import RecordForm
from .models import EXTENSIONS, Record

IMAGE_CSP = "default-src 'none'; img-src 'self'; style-src 'unsafe-inline'; sandbox"


@company_required
def record_list(request):
    """The library: the papers the company keeps, by category, with the selected one beside the list."""
    records = Record.objects.select_related('uploaded_by')
    templates = DocumentTemplate.objects.all()
    # Two independent filters: the category (what kind of paper) and the status (expiring soon or already expired).
    category = request.GET.get('cat', '')
    soon = request.GET.get('status') == 'soon'
    if category not in dict(Record.CATEGORIES):
        category = ''
    if category:
        records = records.filter(category=category)
        templates = templates.filter(category=category)
    expiring = folders.expiring().filter(category=category) if category else folders.expiring()
    if soon:
        records = records.filter(pk__in=expiring.values('pk')).order_by('expiry_date')
        templates = templates.none()                               # a template does not expire
    query = request.GET.get('q', '').strip()[:100]
    if query:
        records = records.filter(Q(title__icontains=query) | Q(doc_type__icontains=query) | Q(issuer__icontains=query) |
                                 Q(reference__icontains=query) | Q(notes__icontains=query))
        templates = templates.filter(name__icontains=query)
    records, templates = list(records), list(templates)
    for row in records:
        row.entry = 'record'
    for row in templates:
        row.entry = 'template'
    entries = sorted(records + templates, key=lambda row: row.created_at, reverse=True) if not soon else records
    selected = None
    for param, entry in (('tpl', 'template'), ('rec', 'record')):
        value = request.GET.get(param, '')
        if value.isdigit():
            selected = next((e for e in entries if e.pk == int(value) and e.entry == entry), None)
            if selected:
                break
    if selected is None and entries:
        selected = entries[0]
    reading = selected is not None and selected.entry == 'record' and Job.objects.filter(
        company=request.company, kind=Job.Kind.CALL, status__in=[Job.Status.PENDING, Job.Status.RUNNING],
        params__func=extract.FUNC, params__record_id=selected.pk).first()
    return render(request, 'library/list.html', {
        'entries': entries, 'selected': selected, 'cat': category, 'soon': soon, 'q': query,
        'expiring_here': expiring.count(), 'cat_label': dict(Record.CATEGORIES).get(category, ''),
        'read_quote': quotes.make(extract.SERVICE), 'reading': reading, 'pdf_available': pdf_tools.available(),
        'imports_left': document_jobs.imports_left(request.company), 'write_quote': document_jobs.quote_for(['fill_document']),
        'design_quote': document_jobs.quote_for(['generate_template']), **folders.folders()})


def _form(request, record, title):
    form = RecordForm(request.POST or None, request.FILES or None, instance=record)
    if request.method == 'POST' and form.is_valid():
        saved = form.save(commit=False)
        saved.company = request.company
        if saved.uploaded_by_id is None:
            saved.uploaded_by = request.user
        if 'expiry_date' in form.changed_data:
            saved.reminded_days = None               # a renewal: the reminders start again for the new date
        new = saved.pk is None
        title_from_file = False
        if form.reading and not saved.title:
            upload = form.cleaned_data.get('file')
            saved.title = (getattr(upload, 'name', '') or '').rsplit('.', 1)[0][:200] or _('Untitled document')
            title_from_file = True
        saved.save()
        audit.record(request, AuditEvent.RECORD_UPLOADED if new else AuditEvent.RECORD_CHANGED, saved.title)
        messages.success(request, _('Saved.'))
        if form.reading:
            # The file is kept whatever happens: a refused payment (middleware: message + wallet) leaves it unread, a failed
            # read is given back. Charged at the quote that was shown (expected_points), never at another price.
            extract.queue(saved, request.user, expected_points(form.cleaned_data), title=title_from_file)
            messages.info(request, _('Reading the document… the details will appear here in a moment.'))
        return redirect(f"{reverse('library:list')}?rec={saved.pk}")
    types = (Record.objects.exclude(doc_type='').values_list('doc_type', flat=True).distinct().order_by('doc_type')[:200])
    return render(request, 'library/form.html', {'form': form, 'record': record, 'page_title': title, 'known_types': types,
                                                 'read_quote': quotes.make(extract.SERVICE)})


@company_required(edit=True)
def upload(request):
    category = request.GET.get('cat')
    record = Record(category=category if category in dict(Record.CATEGORIES) else Record.COMPANY)
    return _form(request, record, _('Upload a document'))


@company_required(edit=True)
def edit(request, pk):
    return _form(request, get_object_or_404(Record, pk=pk), _('Edit the document'))


@company_required(edit=True)
@require_POST
def read(request, pk):
    """Read an uploaded document again and fill the details that are still empty (a paid job, at the quote shown)."""
    record = get_object_or_404(Record, pk=pk)
    extract.queue(record, request.user, expected_points(request.POST))
    messages.info(request, _('Reading the document… the details will appear here in a moment.'))
    return redirect(f"{reverse('library:list')}?rec={record.pk}")


@company_required(manage=True)
@require_POST
def delete(request, pk):
    record = get_object_or_404(Record, pk=pk)
    title = record.title
    record.delete()
    audit.record(request, AuditEvent.RECORD_DELETED, title)
    messages.success(request, _('Deleted.'))
    return redirect('library:list')


@xframe_options_sameorigin
@company_required
def record_file(request, pk):
    """The stored file, for members of the company only; shown in the preview pane or downloaded."""
    record = get_object_or_404(Record, pk=pk)
    name = (slugify(record.title) or 'document') + EXTENSIONS.get(record.content_type, '')
    response = FileResponse(record.file.open('rb'), content_type=record.content_type,
                            as_attachment=request.GET.get('download') == '1', filename=name)
    response['Cache-Control'] = 'private, no-store'
    response['X-Content-Type-Options'] = 'nosniff'
    if record.is_image:
        response['Content-Security-Policy'] = IMAGE_CSP
    return response
