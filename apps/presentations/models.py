import uuid

from django.conf import settings
from django.db import models
from django.utils.translation import gettext_lazy as _

from apps.core.storage import private_storage
from apps.core.tenancy import CompanyScopedModel
from apps.library.models import Record

RTL_LANGUAGES = ('ar', 'fa')


def upload_file(instance, filename):
    # A random name: the title of a deck may carry company details. Encrypted at rest like every private file.
    ext = '.pdf' if str(filename).lower().endswith('.pdf') else '.pptx'
    return f'{instance.company_id}/presentations/{uuid.uuid4().hex}{ext}'


class Presentation(CompanyScopedModel):
    """A PowerPoint the AI built from a topic (and optionally a document of the library), in the company's identity."""

    STANDARD, PREMIUM, ULTRA = 'standard', 'premium', 'ultra'
    TIERS = [(STANDARD, _('Standard')), (PREMIUM, _('Premium')), (ULTRA, _('Ultra'))]
    QUEUED, RUNNING, DONE, FAILED = 'queued', 'running', 'done', 'failed'
    STATUSES = [(QUEUED, _('Waiting')), (RUNNING, _('Working')), (DONE, _('Done')), (FAILED, _('Failed'))]
    MIN_SLIDES, MAX_SLIDES = 5, 20

    title = models.CharField(_('title'), max_length=200)
    brief = models.TextField(_('what is it about?'), max_length=8000)
    language = models.CharField(_('language of the slides'), max_length=8, choices=settings.LANGUAGES)
    slides = models.PositiveSmallIntegerField(_('number of slides'), default=10)
    tier = models.CharField(_('quality'), max_length=10, choices=TIERS, default=PREMIUM)
    audience = models.CharField(_('who will watch it'), max_length=200, blank=True)
    tone = models.CharField(_('tone'), max_length=200, blank=True)
    source = models.ForeignKey(Record, null=True, blank=True, on_delete=models.SET_NULL, related_name='+', editable=False)
    status = models.CharField(max_length=10, choices=STATUSES, default=QUEUED, db_index=True)
    error = models.CharField(max_length=300, blank=True)
    pptx = models.FileField(upload_to=upload_file, storage=private_storage, blank=True)
    preview = models.FileField(upload_to=upload_file, storage=private_storage, blank=True)
    deck = models.JSONField(default=dict, blank=True)                 # the plan: titles and texts (never the files)
    units = models.DecimalField(max_digits=6, decimal_places=2, default=0, help_text='Slides and source pages: the basis of the price.')
    source_pages = models.PositiveSmallIntegerField(default=0)
    job_id = models.PositiveIntegerField(null=True, blank=True, editable=False)            # the paid job that builds it
    created_by = models.ForeignKey(settings.AUTH_USER_MODEL, null=True, blank=True, on_delete=models.SET_NULL,
                                   related_name='+', editable=False)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ['-created_at', '-id']

    def __str__(self):
        return self.title

    @property
    def is_working(self):
        return self.status in (self.QUEUED, self.RUNNING)

    @property
    def is_rtl(self):
        return self.language in RTL_LANGUAGES

    @property
    def outline(self):
        return [s.get('title') or s.get('quote') or '' for s in (self.deck or {}).get('slides', [])]
