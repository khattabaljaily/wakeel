import uuid

from django.conf import settings
from django.db import models
from django.utils import timezone
from django.utils.translation import gettext_lazy as _

from apps.core.storage import private_storage
from apps.core.tenancy import CompanyScopedModel

# A document whose expiry is this close counts as "expiring soon" on the board and in the list.
SOON_DAYS = 30
EXTENSIONS = {'application/pdf': '.pdf', 'image/png': '.png', 'image/jpeg': '.jpg', 'image/webp': '.webp'}


def upload_record(instance, filename):
    # The first part is the company id (the key of the encrypted storage); a random name, and the extension of the type
    # we detected, never the one the uploader chose.
    return f'{instance.company_id}/records/{uuid.uuid4().hex}{EXTENSIONS.get(instance.content_type, "")}'


class Record(CompanyScopedModel):
    """An official document the company keeps: a licence, a registration, a contract, an invoice."""

    # Few and broad on purpose, grouped by who in the company looks after the papers. The detail lives in the free-text
    # `doc_type` ("Commercial Registration", "Iqama", "Gewerbeanmeldung"), never in a longer list of categories.
    COMPANY, FINANCE, EMPLOYEES, CONTRACTS = 'company', 'finance', 'employees', 'contracts'
    LETTERS, OTHER = 'letters', 'other'
    CATEGORIES = [
        (COMPANY, _('Company and legal documents')),
        (FINANCE, _('Financial documents')),
        (EMPLOYEES, _('Employee documents')),
        (CONTRACTS, _('Contracts and agreements')),
        (LETTERS, _('Letters and certificates')),
        (OTHER, _('Other documents')),
    ]

    category = models.CharField(_('category'), max_length=20, choices=CATEGORIES, default=COMPANY)
    title = models.CharField(_('name'), max_length=200)
    doc_type = models.CharField(_('document type'), max_length=200, blank=True)
    issuer = models.CharField(_('issued by'), max_length=200, blank=True)
    reference = models.CharField(_('reference no.'), max_length=100, blank=True)
    issue_date = models.DateField(_('issue date'), null=True, blank=True)
    expiry_date = models.DateField(_('expiry date'), null=True, blank=True)
    notes = models.TextField(_('notes'), blank=True)
    file = models.FileField(_('file'), upload_to=upload_record, storage=private_storage)
    content_type = models.CharField(max_length=40, editable=False)
    size = models.PositiveIntegerField(default=0, editable=False)
    # The last reminder stage sent for the current expiry date (90, 30, 7, 1 or 0 days before); cleared when it changes.
    reminded_days = models.SmallIntegerField(null=True, blank=True, editable=False)
    uploaded_by = models.ForeignKey(settings.AUTH_USER_MODEL, null=True, blank=True, on_delete=models.SET_NULL,
                                    related_name='+', editable=False)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        ordering = ['-created_at', '-id']
        indexes = [models.Index(fields=['company', 'expiry_date'])]

    def __str__(self):
        return self.title

    @property
    def days_left(self):
        if self.expiry_date is None:
            return None
        return (self.expiry_date - timezone.localdate()).days

    @property
    def status(self):
        """'expired', 'soon', 'valid', or '' when the document does not expire."""
        days = self.days_left
        if days is None:
            return ''
        return 'expired' if days < 0 else 'soon' if days <= SOON_DAYS else 'valid'

    @property
    def is_image(self):
        return self.content_type.startswith('image/')
