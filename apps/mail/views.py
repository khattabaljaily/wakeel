"""The company's mailbox inside Wakeel. One mailbox per company: owners and administrators connect it, the members who can
edit read and write with it. Connecting, opening a message and sending one are written in the activity log. No message is
kept here: everything is read from the company's mail server when a page is opened."""
import html as html_lib
import io
import re
from functools import wraps
from urllib.parse import urlencode

from django.contrib import messages
from django.core.cache import cache
from django.http import FileResponse, Http404, HttpResponse, JsonResponse
from django.shortcuts import get_object_or_404, redirect, render
from django.urls import reverse
from django.utils import timezone
from django.utils.translation import gettext as _
from django.utils.translation import gettext_lazy, pgettext_lazy
from django.views.decorators.http import require_POST

from apps.audit import log as audit
from apps.audit.models import AuditEvent
from apps.companies.decorators import company_required
from apps.credits.catalog import format_points
from apps.credits.charging import get_wallet
from apps.credits.jobs import expected_points

from . import client, generate, htmlsafe
from . import render as mailrender
from .client import AuthFailed, MailError
from .forms import SetupForm, TemplateForm, split_recipients
from .models import MailAccount, MailTemplate

SENDS_PER_HOUR = 60
MAX_RECIPIENTS = 30
MAX_FILES = 10
MAX_DOCS = 5


def _no_store(decorator):
    """The access check, and the browser keeps no copy of a mail page."""
    def wrap(view):
        @decorator
        @wraps(view)
        def wrapper(request, *args, **kwargs):
            response = view(request, *args, **kwargs)
            response['Cache-Control'] = 'private, no-store'
            return response
        return wrapper
    return wrap


editor = _no_store(company_required(edit=True))          # owners, administrators and editors read and write
manager = _no_store(company_required(manage=True))       # owners and administrators connect and disconnect it


def _account():
    return MailAccount.objects.first()


def _failed(request, account, exc):
    """A mail-server problem: say what it is; a refused password is remembered so the owner sees it."""
    if isinstance(exc, AuthFailed):
        MailAccount.all_companies.filter(pk=account.pk).update(last_error=str(exc)[:300])
    return render(request, 'mail/error.html', {'account': account, 'error': str(exc), 'auth': isinstance(exc, AuthFailed),
                                               'can_manage': request.membership.can_manage}, status=502)


@editor
def home(request):
    return redirect('mail:box') if _account() else render(request, 'mail/not_connected.html', {'can_manage': request.membership.can_manage})


SETUP_FIELDS = ('address', 'display_name', 'username', 'imap_host', 'imap_port', 'imap_security', 'smtp_host', 'smtp_port',
                'smtp_security', 'signature')


@manager
def setup(request):
    account = _account()
    initial = {f: getattr(account, f) for f in SETUP_FIELDS} if account else {}
    form = SetupForm(request.POST or None, initial=initial, existing=account)
    advanced = bool(account)
    if request.method == 'POST' and form.is_valid():
        data = form.cleaned_data
        candidate = account or MailAccount(company=request.company, connected_by=request.user)
        for key in SETUP_FIELDS:
            setattr(candidate, key, data[key])
        password = data['password'] or (account.get_password() if account else '')
        try:
            client.check_settings(candidate, password)
        except MailError as exc:
            form.add_error(None, f'{exc} ({candidate.imap_host}:{candidate.imap_port} / {candidate.smtp_host}:{candidate.smtp_port})')
            advanced = True
        else:
            if data['password']:
                candidate.set_password(password)
            candidate.last_error = ''
            candidate.connected_by = request.user
            candidate.save()
            client.drop_connections(candidate)
            audit.record(request, AuditEvent.MAIL_CONNECTED, candidate.address)
            messages.success(request, _('The mailbox is connected.'))
            return redirect('mail:box')
    elif request.method == 'POST':
        advanced = True
    return render(request, 'mail/setup.html', {'form': form, 'account': account, 'advanced': advanced})


@manager
@require_POST
def disconnect(request):
    account = _account()
    if account:
        address = account.address
        client.drop_connections(account)
        account.delete()
        audit.record(request, AuditEvent.MAIL_DISCONNECTED, address)
        messages.success(request, _('The mailbox is disconnected and its password is deleted. Your messages stay on your mail server.'))
    return redirect('mail:home')


LABELS = {'inbox': gettext_lazy('Inbox'), 'drafts': gettext_lazy('Drafts'), 'sent': gettext_lazy('Sent'),
          'archive': pgettext_lazy('mail folder', 'Archive'), 'junk': gettext_lazy('Junk'), 'trash': gettext_lazy('Trash')}
ICONS = {'inbox': 'bi-inbox', 'sent': 'bi-send', 'drafts': 'bi-pencil', 'archive': 'bi-archive', 'junk': 'bi-slash-circle', 'trash': 'bi-trash'}


def _label(folders):
    """The usual folders carry our own (translated) names; a second folder of the same kind keeps the server's name."""
    taken = set()
    for f in folders:
        f.label = str(LABELS[f.role]) if f.role in LABELS and f.role not in taken else f.name
        f.bi = ICONS.get(f.role, 'bi-folder')
        taken.add(f.role)


def _avatar(name, address):
    """The letter and the colour of the round badge that stands for a sender."""
    letter = next((c for c in (name or address or '?') if c.isalnum()), '?').upper()
    return letter, sum(ord(c) for c in (address or name).lower()) * 37 % 360


def _page_number(value):
    try:
        return max(1, int(value))
    except (TypeError, ValueError):
        return 1


def _stamp(summaries):
    today = timezone.localdate()
    for s in summaries:
        if s.date is not None:
            local = timezone.localtime(s.date) if timezone.is_aware(s.date) else s.date
            s.today, s.local_date = local.date() == today, local
        else:
            s.today, s.local_date = False, None
        s.initial, s.hue = _avatar(s.sender, s.sender_address)
    return summaries


@editor
def box(request):
    account = _account()
    if account is None:
        return redirect('mail:home')
    wanted, query, page = request.GET.get('f', 'INBOX'), (request.GET.get('q') or '').strip()[:100], _page_number(request.GET.get('page'))
    uid = request.GET.get('m', '')
    try:
        with client.Mailbox(account) as mb:
            folder = mb.folder(wanted) or mb.folder('INBOX')
            if folder is None:
                raise MailError(_('The mailbox has no Inbox.'))
            summaries, total, page = mb.list(folder, page, query)
            inbox = mb.role_folder('inbox') or folder
            unread = mb.unread(inbox)
            folders = mb.folders()
            _label(folders)
            _label([folder])
            selected = None
            if uid.isdigit():
                selected = mb.message(folder, int(uid))
                if selected is None:
                    messages.error(request, _('That message is not there any more.'))
                else:
                    audit.record(request, AuditEvent.MAIL_OPENED, account.address, sender=selected.sender_address)
    except MailError as exc:
        return _failed(request, account, exc)
    pages = -(-total // client.PAGE) if total else 1
    if selected is not None:
        fragment, hidden = htmlsafe.clean(selected.html) if selected.html else ('', 0)
        selected.hidden_images = hidden
        selected.frame = htmlsafe.frame_document(fragment or htmlsafe.from_text(selected.text))
        selected.shown_date = timezone.localtime(selected.date) if selected.date and timezone.is_aware(selected.date) else selected.date
        selected.files = [a for a in selected.attachments if not a.inline]
        for a in selected.files:
            a.keepable = a.content_type in ('application/pdf', 'image/png', 'image/jpeg', 'image/webp')
        selected.initial, selected.hue = _avatar(selected.sender, selected.sender_address)
    return render(request, 'mail/box.html', {
        'account': account, 'folders': folders, 'folder': folder, 'inbox': inbox, 'unread': unread, 'summaries': _stamp(summaries),
        'total': total, 'page': page, 'pages': pages, 'q': query, 'selected': selected,
        'prev': page - 1 if page > 1 else None, 'next': page + 1 if page < pages else None,
        'can_manage': request.membership.can_manage})


@editor
def attachment(request, uid, index):
    account = _account()
    if account is None:
        raise Http404
    try:
        with client.Mailbox(account) as mb:
            folder = mb.folder(request.GET.get('f', 'INBOX'))
            found = mb.attachment(folder, uid, index) if folder else None
    except MailError as exc:
        return _failed(request, account, exc)
    if not found:
        raise Http404
    name, _content_type, data = found
    response = FileResponse(io.BytesIO(data), as_attachment=True, filename=name)
    response['X-Content-Type-Options'] = 'nosniff'
    response['Content-Security-Policy'] = "default-src 'none'; sandbox"
    return response


@editor
@require_POST
def act(request):
    """One thing to do with one message: mark read or unread, star, archive, mark as junk, delete."""
    account = _account()
    if account is None:
        raise Http404
    op, uid = request.POST.get('op', ''), request.POST.get('uid', '')
    if not uid.isdigit() or op not in ('unread', 'read', 'star', 'unstar', 'archive', 'junk', 'delete'):
        raise Http404
    uid = int(uid)
    back = None
    try:
        with client.Mailbox(account) as mb:
            folder = mb.folder(request.POST.get('f', 'INBOX'))
            if folder is None:
                raise Http404
            back = reverse('mail:box') + '?' + urlencode({'f': folder.raw})
            if op in ('read', 'unread'):
                mb.flag(folder, uid, '\\Seen', op == 'read')
                back += f'&m={uid}' if op == 'read' else ''
            elif op in ('star', 'unstar'):
                mb.flag(folder, uid, '\\Flagged', op == 'star')
                back += f'&m={uid}'
            elif op == 'delete':
                mb.delete(folder, uid)
            else:
                target = mb.role_folder('archive' if op == 'archive' else 'junk')
                if target is None:
                    messages.error(request, _('This mailbox has no such folder.'))
                    back += f'&m={uid}'
                else:
                    mb.move(folder, uid, target)
    except MailError as exc:
        return _failed(request, account, exc)
    return redirect(back or 'mail:box')


def _text_of(message):
    if message.text:
        return message.text
    return html_lib.unescape(re.sub(r'<[^>]+>', ' ', re.sub(r'(?is)<(script|style).*?</\1>|<br\s*/?>|</p>', '\n', message.html or '')))


def _html_lines(text):
    return '<br>'.join(html_lib.escape(line) for line in (text or '').splitlines())


def _plain_to_html(text):
    return ''.join(f'<p>{_html_lines(chunk) or "<br>"}</p>' for chunk in (text or '').replace('\r\n', '\n').split('\n\n')) or '<p><br></p>'


def _quoted_html(message):
    when = message.date.strftime('%Y-%m-%d %H:%M') if message.date else ''
    who = _('On %(date)s, %(who)s wrote:') % {'date': when, 'who': f'{message.sender} <{message.sender_address}>'}
    return f'<p><br></p><p>{html_lib.escape(who)}</p><blockquote>{_html_lines(_text_of(message).strip())}</blockquote>'


def _is_rtl(text):
    return bool(re.search('[؀-ۿݐ-ݿ]', text or ''))


def _template_of(value):
    return MailTemplate.objects.filter(pk=int(value)).first() if str(value or '').isdigit() else None


def compose_message(request, subject, raw_html, template=None, for_preview=False):
    """(plain text, the finished page, rtl, logo part) of a message: its body made safe, then put into the template (or a plain
    page). On screen the logo is a data address; in a sent message it travels as an inline attachment (cid:logo)."""
    body, _images = htmlsafe.clean(raw_html)
    text = mailrender.to_text(body)
    company = request.company
    rtl = (template.language in ('ar', 'fa')) if template else _is_rtl(text)
    if template:
        logo = mailrender.logo_data_uri(company) if for_preview else ('cid:logo' if mailrender.logo_part(company) else '')
        inner = mailrender.fill(template.html, body, subject, mailrender.company_values(company, template.language), logo)
    else:
        inner = mailrender.plain_wrapper(body, rtl)
    page = mailrender.document(inner, rtl)
    return text, page, rtl, (mailrender.logo_part(company) if template and 'cid:logo' in page else None)


@editor
@require_POST
def preview(request):
    """The message as the recipient will see it, in the chosen template: a page for the preview frame."""
    raw = request.POST.get('body_html')
    if raw is None:
        raw = _plain_to_html(request.POST.get('body', ''))
    _text, page, _rtl, _logo = compose_message(request, request.POST.get('subject', '')[:300], raw,
                                               _template_of(request.POST.get('template')), for_preview=True)
    response = HttpResponse(page)
    response['Content-Security-Policy'] = "default-src 'none'; style-src 'unsafe-inline'; img-src data:"
    return response


def compose_extra(request):
    """The company's e-mail templates for the composer (the default one is chosen)."""
    return {'templates': list(MailTemplate.objects.all()), 'designs_template': 'mail/_designs.html'}


@editor
def compose(request):
    account = _account()
    if account is None:
        return redirect('mail:home')
    default = MailTemplate.objects.filter(is_default=True).first()
    values = {'to': request.GET.get('to', ''), 'cc': '', 'bcc': '', 'subject': '', 'body_html': '', 'template': str(default.pk) if default else ''}
    source = None
    ref = request.GET.get('reply') or request.GET.get('reply_all') or request.GET.get('forward') or request.POST.get('ref', '')
    mode = ('reply_all' if request.GET.get('reply_all') else 'reply' if request.GET.get('reply') else
            'forward' if request.GET.get('forward') else request.POST.get('mode', ''))
    folder_raw = request.GET.get('f') or request.POST.get('f', 'INBOX')
    if ref.isdigit():
        try:
            with client.Mailbox(account) as mb:
                folder = mb.folder(folder_raw)
                source = mb.message(folder, int(ref), mark_seen=False) if folder else None
        except MailError as exc:
            return _failed(request, account, exc)
    modal = bool(request.GET.get('modal') or request.POST.get('modal'))

    def page(status=200):
        return render(request, 'mail/_compose_modal.html' if modal else 'mail/compose.html', {
            'account': account, 'values': values, 'ref': ref if source or request.method == 'POST' else '', 'mode': mode, 'f': folder_raw,
            'max_files': MAX_FILES, 'modal': modal, **compose_extra(request)}, status=status)

    def failed(text):
        """A refused message: in the window, as text for the dialog; on a page, as a message above the form."""
        if modal:
            return JsonResponse({'ok': False, 'error': text})
        messages.error(request, text)
        return page()

    if request.method == 'GET':
        signature = f'<p><br></p><p>-- <br>{_html_lines(account.signature)}</p>' if account.signature else ''
        if source is not None:
            subject = source.subject
            if mode == 'forward':
                values['subject'] = subject if re.match(r'(?i)^(fwd?|إعادة توجيه)\s*:', subject) else f'Fwd: {subject}'
                values['body_html'] = ('<p><br></p>' + signature + '<p>---------- ' + html_lib.escape(_('Forwarded message')) + ' ----------</p><blockquote>'
                                       + _html_lines(_text_of(source).strip()) + '</blockquote>')
            else:
                values['subject'] = subject if re.match(r'(?i)^(re|رد)\s*:', subject) else f'Re: {subject}'
                values['to'] = source.reply_to or source.sender_address
                if mode == 'reply_all':
                    values['cc'] = ', '.join(a for a in source.to + source.cc if account.address.lower() not in a.lower())
                values['body_html'] = '<p><br></p>' + signature + _quoted_html(source)
        else:
            values['body_html'] = '<p><br></p>' + signature
        return page()
    # sending
    for key in ('to', 'cc', 'bcc', 'subject', 'template'):
        values[key] = request.POST.get(key, '')
    raw = request.POST.get('body_html')
    if raw is None:                                        # a plain form (no editor): the text typed becomes paragraphs
        raw = _plain_to_html(request.POST.get('body', ''))
    values['body_html'] = htmlsafe.clean(raw)[0]
    to, bad = split_recipients(values['to'])
    cc, bad_cc = split_recipients(values['cc'])
    bcc, bad_bcc = split_recipients(values['bcc'])
    files = request.FILES.getlist('files')
    text = mailrender.to_text(values['body_html'])
    error = ''
    if bad or bad_cc or bad_bcc:
        error = _('“%(text)s” is not a valid e-mail address.') % {'text': bad or bad_cc or bad_bcc}
    elif not to:
        error = _('Add at least one recipient.')
    elif len(set(to + cc + bcc)) > MAX_RECIPIENTS:
        error = _('You can write to %(n)d addresses at most in one message.') % {'n': MAX_RECIPIENTS}
    elif not text and not files and not request.POST.getlist('doc') and not request.POST.getlist('rec'):
        error = _('Write a message or attach a file.')
    elif len(files) > MAX_FILES:
        error = _('Attach %(n)d files at most.') % {'n': MAX_FILES}
    key = f'mail-send:{request.company.pk}'
    if not error:
        cache.add(key, 0, 3600)
        if cache.incr(key) > SENDS_PER_HOUR:
            error = _('Many messages were sent in the last hour. Try again later.')
    if error:
        return failed(error)
    template = _template_of(values['template'])
    text, html_page, _rtl, logo = compose_message(request, values['subject'], values['body_html'], template)
    attachments = [(f.name, f.content_type, f.read()) for f in files]
    kept, problem = _company_attachments(request, request.POST.getlist('doc'), request.POST.getlist('rec'))
    if problem:
        return failed(problem)
    attachments += kept
    try:
        client.send(account, to, cc, bcc, values['subject'], text, attachments, source, html_page, logo)
    except MailError as exc:
        return failed(str(exc))
    audit.record(request, AuditEvent.MAIL_SENT, account.address, to=', '.join(to)[:200], files=len(attachments), template=bool(template))
    messages.success(request, _('The message was sent.'))
    return JsonResponse({'ok': True, 'url': reverse('mail:box')}) if modal else redirect('mail:box')


def _company_attachments(request, doc_ids, rec_ids):
    """The issued documents (as PDF) and the papers of the library chosen to go with a message: ([(name, type, bytes)],
    problem). Only this company's own; an issued document only when it is approved (if approval is on) and not cancelled."""
    from django.utils.text import slugify

    from apps.documents import pdf as pdf_tools
    from apps.documents import views as document_views
    from apps.documents.models import Document
    from apps.library.models import EXTENSIONS, Record
    found = []
    doc_ids = [int(i) for i in doc_ids if str(i).isdigit()][:MAX_DOCS]
    rec_ids = [int(i) for i in rec_ids if str(i).isdigit()][:MAX_FILES]
    if doc_ids and not pdf_tools.available():
        return [], _('PDF files cannot be made on this server right now, so documents cannot be attached.')
    for document in Document.objects.filter(pk__in=doc_ids):
        if document.revoked_at or (request.company.documents_need_approval and not document.is_approved):
            return [], _('“%(title)s” is not approved yet, so it cannot be sent.') % {'title': document.title}
        try:
            found.append((document_views._pdf_name(document), 'application/pdf', document_views._make_pdf(request, document)))
        except pdf_tools.PdfError:
            return [], _('The PDF of “%(title)s” could not be made. Try again.') % {'title': document.title}
    for record in Record.objects.filter(pk__in=rec_ids):
        with record.file.storage.open(record.file.name, 'rb') as f:
            found.append(((slugify(record.title, allow_unicode=True) or 'document') + EXTENSIONS.get(record.content_type, ''),
                          record.content_type or 'application/octet-stream', f.read()))
    return found, ''


@editor
def picker(request):
    """The list the composer opens to attach something of the company: issued documents and papers, with a search."""
    from apps.documents.models import Document
    from apps.library.models import Record
    q = (request.GET.get('q') or '').strip()[:100]
    documents, records = Document.objects.filter(revoked_at__isnull=True), Record.objects.all()
    if q:
        documents, records = documents.filter(title__icontains=q), records.filter(title__icontains=q)
    return render(request, 'mail/_picker.html', {'documents': documents.order_by('-created_at')[:30], 'records': records.order_by('-created_at')[:30], 'q': q})


@editor
@require_POST
def save_attachment(request, uid, index):
    """Keep an attachment of a received message in the company's library (PDF and pictures), then open it to complete the details."""
    from django.core.files.base import ContentFile

    from apps.library.forms import MAX_BYTES, sniff
    from apps.library.models import EXTENSIONS, Record
    account = _account()
    if account is None:
        raise Http404
    try:
        with client.Mailbox(account) as mb:
            folder = mb.folder(request.POST.get('f', 'INBOX'))
            found = mb.attachment(folder, uid, index) if folder else None
    except MailError as exc:
        return _failed(request, account, exc)
    if not found:
        raise Http404
    name, _type, data = found
    upload = ContentFile(data, name=name)
    kind = sniff(upload)
    if kind is None or len(data) > MAX_BYTES:
        messages.error(request, _('Only PDF files and pictures (PNG, JPG, WebP) up to 10 MB can be kept in the library.'))
        return redirect(reverse('mail:box') + '?' + urlencode({'f': folder.raw, 'm': uid}))
    stem = name.rsplit('.', 1)[0][:200] or _('Attachment')
    record = Record(company=request.company, title=stem, category=Record.OTHER, content_type=kind, size=len(data), uploaded_by=request.user)
    record.file.save(f'{stem}{EXTENSIONS[kind]}', ContentFile(data), save=False)
    record.save()
    audit.record(request, AuditEvent.RECORD_UPLOADED, record.title, source='mail')
    messages.success(request, _('Saved in your library. Complete its details here.'))
    return redirect('library:edit', pk=record.pk)


# -- the company's e-mail templates (designed by the AI, paid) --------------------------------------------------------------------

@editor
def templates(request):
    return render(request, 'mail/templates.html', {'templates': MailTemplate.objects.all(), 'quote': generate.quote(),
                                                   'can_manage': request.membership.can_manage})


@editor
def template_new(request):
    """The choice of a style, then a paid job at the price on the button; the page that waits opens the templates when done."""
    company = request.company
    form = TemplateForm(request.POST or None, initial={'language': company.main_language or request.LANGUAGE_CODE, 'style': 'classic'})
    if request.method == 'POST' and form.is_valid():
        # Charged here at the price that was shown (expected_points); a refused payment is answered by the payment middleware.
        job = generate.start(company, request.user, form.cleaned_data, expected_points(request.POST))
        return redirect(f"{reverse('documents:working', args=[job.pk])}?{urlencode({'back': reverse('mail:templates')})}")
    return render(request, 'mail/template_new.html', {'form': form, 'quote': generate.quote(), 'styles': generate.STYLES.items(),
                                                      'balance': format_points(get_wallet(company).balance)})


@editor
def template_preview(request, pk):
    """A template filled with sample text and the company's own details: a page for a preview frame."""
    template = get_object_or_404(MailTemplate, pk=pk)
    company = request.company
    body = mailrender.SAMPLE_BODY_AR if template.language in ('ar', 'fa') else mailrender.SAMPLE_BODY
    page = mailrender.document(mailrender.fill(template.html, body, _('Subject of your message'),
                                               mailrender.company_values(company, template.language), mailrender.logo_data_uri(company)),
                               template.language in ('ar', 'fa'))
    response = HttpResponse(page)
    response['Content-Security-Policy'] = "default-src 'none'; style-src 'unsafe-inline'; img-src data:"
    response['X-Frame-Options'] = 'SAMEORIGIN'
    return response


@editor
@require_POST
def template_default(request, pk):
    template = get_object_or_404(MailTemplate, pk=pk)
    MailTemplate.objects.exclude(pk=template.pk).update(is_default=False)
    template.is_default = True
    template.save(update_fields=['is_default'])
    return redirect('mail:templates')


@manager
@require_POST
def template_delete(request, pk):
    get_object_or_404(MailTemplate, pk=pk).delete()
    messages.success(request, _('Deleted.'))
    return redirect('mail:templates')
