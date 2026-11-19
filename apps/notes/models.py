from zoneinfo import ZoneInfo

from django.conf import settings
from django.db import models
from django.utils import timezone
from django.utils.translation import gettext_lazy as _

from apps.core.tenancy import CompanyScopedModel


class Note(CompanyScopedModel):
    """A member's own note, with an optional reminder. Private: only its owner ever sees it (not even the company's owner)."""

    owner = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.CASCADE, related_name='+', editable=False)
    title = models.CharField(_('title'), max_length=200)
    body = models.TextField(_('note'), blank=True)
    pinned = models.BooleanField(_('pin to the top'), default=False)
    # The moment to remind, stored in UTC; `tz` is the owner's own zone (from their browser) it was typed in and is shown in.
    remind_at = models.DateTimeField(_('remind me at'), null=True, blank=True)
    tz = models.CharField(max_length=64, default='UTC', editable=False)
    reminded_at = models.DateTimeField(null=True, blank=True, editable=False)     # the e-mail went out (or the owner wants none)
    notified_at = models.DateTimeField(null=True, blank=True, editable=False)     # it was put in the notification centre
    done = models.BooleanField(default=False, editable=False)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        ordering = ['-pinned', '-created_at', '-id']
        indexes = [models.Index(fields=['company', 'owner'])]

    def __str__(self):
        return self.title

    @property
    def zone(self):
        try:
            return ZoneInfo(self.tz)
        except Exception:
            return ZoneInfo('UTC')

    @property
    def remind_local(self):
        return timezone.localtime(self.remind_at, self.zone) if self.remind_at else None

    @property
    def remind_display(self):
        local = self.remind_local
        return f'{local:%Y-%m-%d %H:%M}' if local else ''

    @property
    def is_due(self):
        return bool(self.remind_at and not self.done and self.remind_at <= timezone.now())
