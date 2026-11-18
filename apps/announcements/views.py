from functools import wraps

from django.contrib import messages
from django.core.exceptions import PermissionDenied
from django.shortcuts import get_object_or_404, redirect, render
from django.urls import reverse
from django.utils import timezone
from django.utils.translation import gettext as _
from django.views.decorators.http import require_POST

from apps.audit import log as audit
from apps.companies.decorators import company_required
from apps.companies.models import Membership
from apps.notifications.services import mark_read_for, notify_event

from .forms import AnnouncementForm
from .models import Announcement, AnnouncementRead


def _staff(view):
    """Everyone who works in the company reads announcements; an outside client does not."""
    @company_required
    @wraps(view)
    def wrapper(request, *args, **kwargs):
        if request.membership.role == Membership.Role.CLIENT:
            raise PermissionDenied
        return view(request, *args, **kwargs)
    return wrapper


_managers = company_required(manage=True)       # only the owner and the administrators publish, change and delete them


def _publish(request, announcement):
    """Tell the team (the bell, and a push), asking for a confirmation when the announcement needs one."""
    kind = 'announcement_ack' if announcement.requires_ack else 'announcement'
    notify_event([m.user for m in announcement.audience()], kind, company=request.company, actor=request.user,
                 url=reverse('announcements:detail', args=[announcement.pk]), title=announcement.title)


def _list_context(request, form):
    mine = {r.announcement_id: r for r in AnnouncementRead.objects.filter(user=request.user)}
    items = []
    for a in Announcement.objects.select_related('author'):
        read = mine.get(a.pk)
        items.append({'a': a, 'unread': read is None and a.author_id != request.user.pk,
                      'needs_ack': a.requires_ack and a.author_id != request.user.pk and not (read and read.acknowledged_at)})
    show = 'unread' if request.GET.get('show') == 'unread' else 'all'
    unread = sum(1 for i in items if i['unread'])
    if show == 'unread':
        items = [i for i in items if i['unread']]
    return {'items': items, 'show': show, 'unread': unread, 'form': form, 'can_manage': request.membership.can_manage}


@_staff
def announcement_list(request):
    return render(request, 'announcements/list.html', _list_context(request, AnnouncementForm()))


@_managers
def new(request):
    form = AnnouncementForm(request.POST or None)
    if request.method == 'POST' and form.is_valid():
        announcement = form.save(commit=False)
        announcement.company, announcement.author = request.company, request.user
        announcement.save()
        _publish(request, announcement)
        audit.record(request, 'announcement.published', announcement.title)
        messages.success(request, _('The announcement was published.'))
        return redirect('announcements:detail', pk=announcement.pk)
    return render(request, 'announcements/list.html', {**_list_context(request, form), 'open_form': True})


@_staff
def detail(request, pk):
    announcement = get_object_or_404(Announcement.objects.select_related('author'), pk=pk)
    mine = None
    if announcement.author_id != request.user.pk:
        mine, _created = AnnouncementRead.objects.get_or_create(announcement=announcement, user=request.user,
                                                                defaults={'company': request.company})
        mark_read_for(request.user, reverse('announcements:detail', args=[pk]))      # opening it reads its notification
    context = {'announcement': announcement, 'mine': mine, 'can_manage': request.membership.can_manage}
    if request.membership.can_manage:
        reads = {r.user_id: r for r in announcement.reads.all()}
        rows = [(m.user, reads.get(m.user_id)) for m in announcement.audience()]
        context.update(rows=rows, total=len(rows), read_count=sum(1 for _u, r in rows if r),
                       ack_count=sum(1 for _u, r in rows if r and r.acknowledged_at))
    return render(request, 'announcements/detail.html', context)


@_staff
@require_POST
def acknowledge(request, pk):
    announcement = get_object_or_404(Announcement, pk=pk)
    if announcement.requires_ack and announcement.author_id != request.user.pk:
        read, _created = AnnouncementRead.objects.get_or_create(announcement=announcement, user=request.user,
                                                                defaults={'company': request.company})
        if read.acknowledged_at is None:
            read.acknowledged_at = timezone.now()
            read.save(update_fields=['acknowledged_at'])
    return redirect('announcements:detail', pk=pk)


@_managers
def edit(request, pk):
    announcement = get_object_or_404(Announcement, pk=pk)
    form = AnnouncementForm(request.POST or None, instance=announcement)
    if request.method == 'POST' and form.is_valid():
        form.save()
        audit.record(request, 'announcement.updated', announcement.title)
        messages.success(request, _('Saved.'))
        return redirect('announcements:detail', pk=pk)
    return render(request, 'announcements/form.html', {'form': form, 'announcement': announcement})


@_managers
@require_POST
def delete(request, pk):
    announcement = get_object_or_404(Announcement, pk=pk)
    title = announcement.title
    announcement.delete()
    audit.record(request, 'announcement.deleted', title)
    messages.success(request, _('Deleted.'))
    return redirect('announcements:list')
