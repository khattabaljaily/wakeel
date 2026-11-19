from django.conf import settings
from django.db import models
from django.utils.translation import gettext_lazy as _

from apps.companies.models import Membership
from apps.core.tenancy import CompanyScopedModel

# Who an announcement is for: the people who work in the company (a client is outside it).
AUDIENCE_ROLES = (Membership.Role.OWNER, Membership.Role.ADMIN, Membership.Role.EDITOR, Membership.Role.VIEWER)


class Announcement(CompanyScopedModel):
    """A circular, announcement or alert from the owner or an administrator to the whole team, with who has read it."""

    NOTICE, CIRCULAR, ALERT = 'notice', 'circular', 'alert'
    KINDS = [(NOTICE, _('Announcement')), (CIRCULAR, _('Circular')), (ALERT, _('Alert'))]

    kind = models.CharField(_('type'), max_length=10, choices=KINDS, default=NOTICE)
    title = models.CharField(_('title'), max_length=200)
    body = models.TextField(_('text'))
    requires_ack = models.BooleanField(_('ask everyone to confirm they read it'), default=False)
    author = models.ForeignKey(settings.AUTH_USER_MODEL, null=True, blank=True, on_delete=models.SET_NULL,
                               related_name='+', editable=False)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        ordering = ['-created_at', '-id']

    def __str__(self):
        return self.title

    def audience(self):
        """The memberships it is for: the team, not the person who wrote it."""
        people = Membership.objects.filter(company_id=self.company_id, role__in=AUDIENCE_ROLES, user__is_active=True)
        if self.author_id:
            people = people.exclude(user_id=self.author_id)
        return people.select_related('user').order_by('user__first_name', 'user__email')


class AnnouncementRead(CompanyScopedModel):
    """One person opened it (read_at) and, when asked, confirmed they read it (acknowledged_at)."""

    announcement = models.ForeignKey(Announcement, on_delete=models.CASCADE, related_name='reads')
    user = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.CASCADE, related_name='+')
    read_at = models.DateTimeField(auto_now_add=True)
    acknowledged_at = models.DateTimeField(null=True, blank=True)

    class Meta:
        constraints = [models.UniqueConstraint(fields=['announcement', 'user'], name='one_read_per_person')]
