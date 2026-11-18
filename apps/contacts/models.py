from django.conf import settings
from django.db import models
from django.utils import timezone
from django.utils.translation import gettext_lazy as _

from apps.core.tenancy import CompanyScopedModel


class Contact(CompanyScopedModel):
    """One book for the company's clients, suppliers and partners, with how to reach them and what was done with them.
    (`company` is the company the book belongs to; the contact's own firm is `organization`.)"""

    CLIENT, SUPPLIER, PARTNER, OTHER = 'client', 'supplier', 'partner', 'other'
    KINDS = [(CLIENT, _('Client')), (SUPPLIER, _('Supplier')), (PARTNER, _('Partner')), (OTHER, _('Other'))]

    kind = models.CharField(_('type'), max_length=10, choices=KINDS, default=CLIENT)
    name = models.CharField(_('name'), max_length=200)
    organization = models.CharField(_('company'), max_length=200, blank=True)
    job_title = models.CharField(_('job title'), max_length=120, blank=True)
    email = models.EmailField(_('e-mail'), blank=True)
    phone = models.CharField(_('phone'), max_length=40, blank=True)
    address = models.CharField(_('address'), max_length=300, blank=True)
    notes = models.TextField(_('notes'), blank=True)
    created_by = models.ForeignKey(settings.AUTH_USER_MODEL, null=True, blank=True, on_delete=models.SET_NULL,
                                   related_name='+', editable=False)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        ordering = ['name', 'id']
        indexes = [models.Index(fields=['company', 'kind'])]

    def __str__(self):
        return self.name


class Interaction(CompanyScopedModel):
    """A line in a contact's history: a call, a meeting, an e-mail, a note."""

    CALL, MEETING, EMAIL, NOTE = 'call', 'meeting', 'email', 'note'
    KINDS = [(CALL, _('Call')), (MEETING, _('Meeting')), (EMAIL, _('E-mail')), (NOTE, _('Note'))]

    contact = models.ForeignKey(Contact, on_delete=models.CASCADE, related_name='interactions')
    kind = models.CharField(_('type'), max_length=10, choices=KINDS, default=NOTE)
    date = models.DateField(_('date'), default=timezone.localdate)
    body = models.TextField(_('what happened'))
    author = models.ForeignKey(settings.AUTH_USER_MODEL, null=True, blank=True, on_delete=models.SET_NULL,
                               related_name='+')
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ['-date', '-id']
