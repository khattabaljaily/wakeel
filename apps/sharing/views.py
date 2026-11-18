"""Making, listing and cancelling sharing links: for the owner and the admins of the company."""
from django.contrib import messages
from django.core.paginator import Paginator
from django.db.models import Count, Max, Q
from django.shortcuts import get_object_or_404, redirect, render
from django.urls import reverse
from django.utils import timezone
from django.utils.translation import gettext as _
from django.views.decorators.http import require_POST

from apps.audit import log as audit
from apps.audit.models import AuditEvent
from apps.companies.decorators import company_required
from apps.documents.models import Document
from apps.library.models import Record

from .models import DAYS, ShareAccess, ShareLink


_managers_only = company_required(manage=True)         # the owner and the administrators share and cancel


def _target(kind, pk):
    """The paper or the issued document to share, or None when it cannot be shared (a document still waiting for
    approval, rejected or cancelled is not the company's word yet, or any more)."""
    if kind == 'record':
        return get_object_or_404(Record, pk=pk)
    document = get_object_or_404(Document, pk=pk)
    return document if document.status == Document.APPROVED and not document.revoked_at else None


def _absolute(request, link):
    return request.build_absolute_uri(reverse('shared:open', args=[link.token]))


@_managers_only
def new(request, kind, pk):
    if kind not in ('record', 'document'):
        return redirect('sharing:list')
    target = _target(kind, pk)
    if target is None:
        messages.error(request, _('This document cannot be shared: it is not approved, or it was cancelled.'))
        return redirect('documents:issued')
    back = f"{reverse('library:list') if kind == 'record' else reverse('documents:issued')}?{'rec' if kind == 'record' else 'doc'}={pk}"
    if request.method == 'POST':
        try:
            days = int(request.POST.get('days', ''))
        except ValueError:
            days = 0
        password = request.POST.get('password', '')
        if days not in DAYS:
            messages.error(request, _('Choose how long the link works.'))
        elif password and len(password) < 6:
            messages.error(request, _('The password must be at least 6 characters.'))
        else:
            link = ShareLink.make(target, request.user, days, password, request.POST.get('allow_download') == 'on')
            audit.record(request, AuditEvent.SHARE_CREATED, f'{kind} {pk}', title=link.title[:100], days=days,
                         password=link.has_password, download=link.allow_download)
            messages.success(request, _('The link is ready. Copy it and send it.'))
            return redirect(f"{reverse('sharing:list')}?new={link.pk}")
    earlier = ShareLink.objects.filter(**{kind: target}).annotate(
        views=Count('accesses', filter=Q(accesses__action=ShareAccess.VIEW)))[:10]
    return render(request, 'sharing/new.html', {'target': target, 'kind': kind, 'days': DAYS, 'back': back,
                                                 'is_record': kind == 'record', 'earlier': earlier})


@_managers_only
def listing(request):
    now = timezone.now()
    rows = ShareLink.objects.select_related('created_by').annotate(
        views=Count('accesses', filter=Q(accesses__action=ShareAccess.VIEW)),
        last_seen=Max('accesses__created_at', filter=Q(accesses__action=ShareAccess.VIEW)))
    page = Paginator(rows, 25).get_page(request.GET.get('page'))
    new = ShareLink.objects.filter(pk=request.GET['new']).first() if request.GET.get('new', '').isdigit() else None
    return render(request, 'sharing/list.html', {'page': page, 'now': now, 'new': new,
                                                  'new_url': _absolute(request, new) if new else ''})


@_managers_only
def detail(request, pk):
    link = get_object_or_404(ShareLink, pk=pk)
    page = Paginator(link.accesses.all(), 50).get_page(request.GET.get('page'))
    return render(request, 'sharing/detail.html', {'link': link, 'page': page, 'url': _absolute(request, link)})


@_managers_only
@require_POST
def revoke(request, pk):
    link = get_object_or_404(ShareLink, pk=pk)
    if link.revoked_at is None:
        link.revoked_at = timezone.now()
        link.save(update_fields=['revoked_at'])
        audit.record(request, AuditEvent.SHARE_REVOKED, f'link {link.pk}', title=link.title[:100])
    messages.success(request, _('The link is cancelled. It no longer opens.'))
    return redirect('sharing:list')
