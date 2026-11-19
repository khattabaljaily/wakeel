import datetime
import secrets

from django.conf import settings
from django.contrib.auth.hashers import check_password, make_password
from django.db import models
from django.utils import timezone
from django.utils.translation import gettext_lazy as _

from apps.documents.models import Document
from apps.library.models import Record
from apps.core.tenancy import CompanyScopedModel

DAYS = (1, 7, 30, 90)


class ShareLink(CompanyScopedModel):
    """A link that lets somebody outside the company look at one paper or one issued document, until it expires or
    is cancelled. Optionally behind a password; saving a copy is allowed only when the owner turned it on."""

    token = models.CharField(max_length=43, unique=True, editable=False)
    record = models.ForeignKey(Record, null=True, blank=True, on_delete=models.CASCADE, related_name='+')
    document = models.ForeignKey(Document, null=True, blank=True, on_delete=models.CASCADE, related_name='+')
    title = models.CharField(max_length=200)                      # what it was called when it was shared
    password_hash = models.CharField(max_length=128, blank=True)
    allow_download = models.BooleanField(_('allow saving a copy'), default=False)
    expires_at = models.DateTimeField()
    revoked_at = models.DateTimeField(null=True, blank=True)
    created_by = models.ForeignKey(settings.AUTH_USER_MODEL, null=True, blank=True, on_delete=models.SET_NULL, related_name='+')
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ['-created_at', '-id']

    def __str__(self):
        return self.title

    @classmethod
    def make(cls, target, user, days, password='', allow_download=False):
        link = cls(title=target.title[:200], created_by=user, allow_download=allow_download,
                   expires_at=timezone.now() + datetime.timedelta(days=days), token=secrets.token_urlsafe(24),
                   company=target.company)
        if isinstance(target, Record):
            link.record = target
        else:
            link.document = target
        if password:
            link.password_hash = make_password(password)
        link.save()
        return link

    @property
    def target(self):
        return self.record or self.document

    @property
    def status(self):
        if self.revoked_at:
            return 'revoked'
        return 'expired' if self.expires_at <= timezone.now() else 'active'

    @property
    def has_password(self):
        return bool(self.password_hash)

    def password_ok(self, raw):
        return bool(self.password_hash) and check_password(raw or '', self.password_hash)


class ShareAccess(CompanyScopedModel):
    """One thing a visitor did with a link: who (address and browser), when."""

    VIEW, DOWNLOAD, WRONG_PASSWORD = 'view', 'download', 'wrong_password'
    ACTIONS = [(VIEW, _('Viewed')), (DOWNLOAD, _('Saved a copy')), (WRONG_PASSWORD, _('Wrong password'))]

    link = models.ForeignKey(ShareLink, on_delete=models.CASCADE, related_name='accesses')
    action = models.CharField(max_length=16, choices=ACTIONS)
    ip = models.GenericIPAddressField(null=True, blank=True)
    agent = models.CharField(max_length=200, blank=True)
    created_at = models.DateTimeField(auto_now_add=True, db_index=True)

    class Meta:
        ordering = ['-created_at', '-id']
