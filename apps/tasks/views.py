from functools import wraps

from django.contrib import messages
from django.core.exceptions import PermissionDenied
from django.http import FileResponse
from django.shortcuts import get_object_or_404, redirect, render
from django.urls import reverse
from django.utils.translation import gettext as _
from django.views.decorators.http import require_POST

from apps.audit import log as audit
from apps.companies.decorators import company_required
from apps.companies.models import Membership
from apps.notifications.services import notify_event, who

from .forms import AttachmentForm, TaskForm
from .models import Task, TaskAttachment, TaskComment


def _member(view):
    """The company's own people read the tasks; an outside client of the company does not see its internal work."""
    @company_required
    @wraps(view)
    def wrapper(request, *args, **kwargs):
        if request.membership.role == Membership.Role.CLIENT:
            raise PermissionDenied
        return view(request, *args, **kwargs)
    return wrapper


_editor = company_required(edit=True)        # viewers read; owners, administrators and editors change things


def _tell_assignee(request, task):
    """The person a task is given to is told (not when they gave it to themselves)."""
    if task.assignee_id:
        notify_event(task.assignee, 'task_assigned', company=request.company, url=reverse('tasks:detail', args=[task.pk]),
                     actor=request.user, who=who(request.user), title=task.title)


def _can_delete(request, task):
    return request.membership.can_manage or task.created_by_id == request.user.pk


def _list_context(request, form):
    view = request.GET.get('show', 'open')
    tasks = Task.objects.select_related('assignee')
    counts = {'open': tasks.exclude(status=Task.DONE).count(), 'mine': tasks.filter(assignee=request.user).exclude(status=Task.DONE).count(),
              'done': tasks.filter(status=Task.DONE).count()}
    if view == 'mine':
        tasks = tasks.filter(assignee=request.user).exclude(status=Task.DONE)
    elif view == 'done':
        tasks = tasks.filter(status=Task.DONE).order_by('-completed_at')
    else:
        view = 'open'
        tasks = tasks.exclude(status=Task.DONE)
    if view != 'done':
        tasks = sorted(tasks, key=lambda t: (t.due_date is None, t.due_date, t.created_at))
    return {'tasks': tasks, 'view': view, 'counts': counts, 'can_edit': request.membership.can_edit, 'form': form}


@_member
def task_list(request):
    return render(request, 'tasks/list.html', _list_context(request, TaskForm(company=request.company)))


@_editor
def new(request):
    form = TaskForm(request.POST or None, company=request.company)
    if request.method == 'POST' and form.is_valid():
        task = form.save(commit=False)
        task.company, task.created_by = request.company, request.user
        task.save()
        audit.record(request, 'task.created', task.title)
        _tell_assignee(request, task)
        messages.success(request, _('The task was added.'))
        return redirect('tasks:detail', pk=task.pk)
    # The form opens over the list: a refused form opens it again with its errors; its address opens it too.
    return render(request, 'tasks/list.html', {**_list_context(request, form), 'open_form': True})


@_editor
def edit(request, pk):
    task = get_object_or_404(Task, pk=pk)
    form = TaskForm(request.POST or None, instance=task, company=request.company)
    if request.method == 'POST' and form.is_valid():
        form.save()
        audit.record(request, 'task.updated', task.title)
        if 'assignee' in form.changed_data:
            _tell_assignee(request, task)
        messages.success(request, _('Saved.'))
        return redirect('tasks:detail', pk=task.pk)
    return render(request, 'tasks/form.html', {'form': form, 'task': task})


@_member
def detail(request, pk):
    task = get_object_or_404(Task.objects.select_related('assignee', 'created_by'), pk=pk)
    return render(request, 'tasks/detail.html', {
        'task': task, 'attachments': task.attachments.all(), 'comments': task.comments.select_related('author'),
        'statuses': Task.STATUSES, 'can_edit': request.membership.can_edit, 'can_delete': _can_delete(request, task),
        'attach_form': AttachmentForm()})


@_editor
@require_POST
def set_status(request, pk):
    task = get_object_or_404(Task, pk=pk)
    status = request.POST.get('status')
    if status in dict(Task.STATUSES) and status != task.status:
        task.set_status(status)
        task.save(update_fields=['status', 'completed_at', 'updated_at'])
        audit.record(request, 'task.status', task.title, status=status)
    return redirect('tasks:detail', pk=task.pk)


@_editor
@require_POST
def delete(request, pk):
    task = get_object_or_404(Task, pk=pk)
    if not _can_delete(request, task):
        raise PermissionDenied
    title = task.title
    for attachment in task.attachments.all():
        attachment.file.delete(save=False)
    task.delete()
    audit.record(request, 'task.deleted', title)
    messages.success(request, _('Deleted.'))
    return redirect('tasks:list')


@_editor
@require_POST
def comment(request, pk):
    task = get_object_or_404(Task, pk=pk)
    body = request.POST.get('body', '').strip()
    if body:
        TaskComment.objects.create(company=request.company, task=task, author=request.user, body=body[:4000])
        others = {u.pk: u for u in (task.assignee, task.created_by) if u is not None}
        notify_event(list(others.values()), 'task_comment', company=request.company, url=reverse('tasks:detail', args=[task.pk]),
                     actor=request.user, who=who(request.user), title=task.title)
    return redirect('tasks:detail', pk=task.pk)


@_editor
@require_POST
def attach(request, pk):
    task = get_object_or_404(Task, pk=pk)
    form = AttachmentForm(request.POST, request.FILES)
    if form.is_valid():
        upload = form.cleaned_data['file']
        attachment = TaskAttachment(company=request.company, task=task, name=(upload.name or _('File'))[:200], size=upload.size,
                                    uploaded_by=request.user)
        attachment.file.save(upload.name, upload, save=False)
        attachment.save()
        audit.record(request, 'task.attached', task.title, file=attachment.name)
    else:
        for errors in form.errors.values():
            for error in errors:
                messages.error(request, error)
    return redirect('tasks:detail', pk=task.pk)


@_member
def attachment_file(request, pk):
    """Always sent as a download, as an opaque file: a member's upload is never shown by the browser itself."""
    attachment = get_object_or_404(TaskAttachment, pk=pk)
    response = FileResponse(attachment.file.open('rb'), content_type='application/octet-stream',
                            as_attachment=True, filename=attachment.name)
    response['Cache-Control'] = 'private, no-store'
    response['X-Content-Type-Options'] = 'nosniff'
    return response


@_editor
@require_POST
def attachment_delete(request, pk):
    attachment = get_object_or_404(TaskAttachment, pk=pk)
    task_pk = attachment.task_id
    attachment.file.delete(save=False)
    attachment.delete()
    audit.record(request, 'task.file_removed', attachment.name)
    return redirect('tasks:detail', pk=task_pk)
