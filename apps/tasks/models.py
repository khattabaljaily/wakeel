import uuid

from django.conf import settings
from django.db import models
from django.utils import timezone
from django.utils.translation import gettext_lazy as _

from apps.core.storage import private_storage
from apps.core.tenancy import CompanyScopedModel


def upload_attachment(instance, filename):
    # A random name: the uploader's own name is kept apart, in `name`, and never used as a path. Encrypted at rest.
    return f'{instance.company_id}/tasks/{uuid.uuid4().hex}'


class Task(CompanyScopedModel):
    """A piece of work for the team: who does it, by when, with the files it needs."""

    TODO, DOING, DONE = 'todo', 'doing', 'done'
    STATUSES = [(TODO, _('To do')), (DOING, _('In progress')), (DONE, _('Done'))]
    LOW, NORMAL, HIGH = 'low', 'normal', 'high'
    PRIORITIES = [(LOW, _('Low')), (NORMAL, _('Normal')), (HIGH, _('High'))]

    title = models.CharField(_('title'), max_length=200)
    description = models.TextField(_('details'), blank=True)
    status = models.CharField(_('status'), max_length=10, choices=STATUSES, default=TODO)
    priority = models.CharField(_('priority'), max_length=10, choices=PRIORITIES, default=NORMAL)
    due_date = models.DateField(_('due date'), null=True, blank=True)
    assignee = models.ForeignKey(settings.AUTH_USER_MODEL, null=True, blank=True, on_delete=models.SET_NULL,
                                 related_name='+', verbose_name=_('assigned to'))
    created_by = models.ForeignKey(settings.AUTH_USER_MODEL, null=True, blank=True, on_delete=models.SET_NULL,
                                   related_name='+', editable=False)
    completed_at = models.DateTimeField(null=True, blank=True, editable=False)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        ordering = ['-created_at', '-id']
        indexes = [models.Index(fields=['company', 'status']), models.Index(fields=['company', 'assignee'])]

    def __str__(self):
        return self.title

    @property
    def is_done(self):
        return self.status == self.DONE

    @property
    def is_overdue(self):
        return bool(self.due_date and not self.is_done and self.due_date < timezone.localdate())

    def set_status(self, status):
        self.status = status
        self.completed_at = timezone.now() if status == self.DONE else None


class TaskAttachment(CompanyScopedModel):
    task = models.ForeignKey(Task, on_delete=models.CASCADE, related_name='attachments')
    file = models.FileField(upload_to=upload_attachment, storage=private_storage)
    name = models.CharField(max_length=200)
    size = models.PositiveIntegerField(default=0, editable=False)
    uploaded_by = models.ForeignKey(settings.AUTH_USER_MODEL, null=True, blank=True, on_delete=models.SET_NULL,
                                    related_name='+', editable=False)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ['created_at', 'id']

    def __str__(self):
        return self.name


class TaskComment(CompanyScopedModel):
    task = models.ForeignKey(Task, on_delete=models.CASCADE, related_name='comments')
    author = models.ForeignKey(settings.AUTH_USER_MODEL, null=True, blank=True, on_delete=models.SET_NULL,
                               related_name='+')
    body = models.TextField()
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ['created_at', 'id']
