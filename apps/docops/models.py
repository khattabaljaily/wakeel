import uuid

from django.conf import settings
from django.db import models
from django.utils.translation import gettext_lazy as _

from apps.core.storage import private_storage
from apps.core.tenancy import CompanyScopedModel
from apps.library.models import Record

RTL_LANGUAGES = ('ar', 'fa')


def upload_result(instance, filename):
    # A random name (the extension of the file kind only): the file of a result is encrypted at rest like the documents.
    ext = '.pdf' if str(filename).lower().endswith('.pdf') else '.docx'
    return f'{instance.company_id}/results/{uuid.uuid4().hex}{ext}'


class Operation(CompanyScopedModel):
    """The saved result of one operation on an uploaded document: a translation, a summary, extracted data, or the
    document turned into an editable Word file."""

    TRANSLATE, SUMMARIZE, EXTRACT, WORD, OCR = 'translate', 'summarize', 'extract', 'word', 'ocr'
    KINDS = [(TRANSLATE, _('Translation')), (SUMMARIZE, _('Summary')), (EXTRACT, _('Extracted data')), (WORD, _('Word file')),
             (OCR, _('Extracted text'))]
    STANDARD, FORMATTED, PREMIUM = 'standard', 'formatted', 'premium'
    TIERS = [(STANDARD, _('Standard')), (FORMATTED, _('Formatted PDF')), (PREMIUM, _('Original design'))]
    QUEUED, RUNNING, DONE, FAILED = 'queued', 'running', 'done', 'failed'
    STATUSES = [(QUEUED, _('Waiting')), (RUNNING, _('Working')), (DONE, _('Done')), (FAILED, _('Failed'))]
    SHORT, MEDIUM, DETAILED = 'short', 'medium', 'detailed'
    LENGTHS = [(SHORT, _('Short')), (MEDIUM, _('Medium')), (DETAILED, _('Detailed'))]

    record = models.ForeignKey(Record, on_delete=models.CASCADE, related_name='operations')
    kind = models.CharField(max_length=10, choices=KINDS)
    language = models.CharField(max_length=8, choices=settings.LANGUAGES)
    # Translation and summary: plain text, shown escaped. Extracted data: {"parties": [...], "dates": [...], ...}.
    text = models.TextField(blank=True)
    data = models.JSONField(default=dict, blank=True)
    length = models.CharField(max_length=10, choices=LENGTHS, blank=True)          # summaries
    tier = models.CharField(max_length=10, choices=TIERS, default=STANDARD)
    source_language = models.CharField(max_length=8, blank=True)                     # translations; '' = detected
    status = models.CharField(max_length=10, choices=STATUSES, default=DONE, db_index=True)
    error = models.CharField(max_length=300, blank=True)                             # why it failed (safe to show)
    file = models.FileField(upload_to=upload_result, storage=private_storage, blank=True)   # the Word file of a conversion
    pages = models.PositiveSmallIntegerField(default=0, help_text='Pages that were read.')
    pages_total = models.PositiveSmallIntegerField(default=0)
    page_units = models.DecimalField(max_digits=6, decimal_places=2, null=True, blank=True,
                                     help_text='What the pages read are worth in dense pages (the basis of the price).')
    job_id = models.PositiveIntegerField(null=True, blank=True, editable=False)      # the paid job that makes it (its progress)
    created_by = models.ForeignKey(settings.AUTH_USER_MODEL, null=True, blank=True, on_delete=models.SET_NULL,
                                   related_name='+', editable=False)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ['-created_at', '-id']

    def __str__(self):
        return f'{self.get_kind_display()} ({self.language}): {self.record}'

    @property
    def is_rtl(self):
        return self.language in RTL_LANGUAGES

    @property
    def was_cut(self):
        return self.pages_total > self.pages

    @property
    def is_working(self):
        return self.status in (self.QUEUED, self.RUNNING)
