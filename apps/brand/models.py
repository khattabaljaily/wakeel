import uuid

from django.conf import settings
from django.db import models
from django.utils.translation import gettext_lazy as _

from apps.core.storage import private_storage
from apps.core.tenancy import CompanyScopedModel


class BrandKit(CompanyScopedModel):
    """What is decided about a company's brand: the chosen symbol, the palette, the font pairing and the personality. Every element
    created later is designed from it, so the whole identity stays consistent. One per company."""

    palette = models.JSONField(default=dict, blank=True)             # {'primary': '#4A1F3D', 'secondary': ..., 'accent': ...}
    pairing = models.CharField(max_length=30, blank=True)
    keywords = models.JSONField(default=list, blank=True)
    personality = models.TextField(blank=True)
    symbol = models.TextField(blank=True)                            # the chosen logo symbol: a sanitised SVG
    chosen_name = models.CharField(max_length=120, blank=True)
    bundle_tier = models.CharField(max_length=10, blank=True)        # 'standard' | 'premium' while a whole kit is being made (20% off)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        constraints = [models.UniqueConstraint(fields=['company'], name='one_brand_kit_per_company')]


def upload_file(instance, filename):
    # A random name: the designs are the company's own and are encrypted at rest like every private file.
    ext = '.' + filename.rsplit('.', 1)[-1].lower() if '.' in filename else ''
    return f'{instance.company_id}/brand/{uuid.uuid4().hex}{ext}'


class BrandAsset(CompanyScopedModel):
    """One purchase: an element of the brand kit in one tier, with the files that came out of it."""

    STANDARD, PREMIUM = 'standard', 'premium'
    TIERS = [(STANDARD, _('Standard')), (PREMIUM, _('Premium'))]
    QUEUED, RUNNING, DONE, FAILED = 'queued', 'running', 'done', 'failed'
    STATUSES = [(QUEUED, _('Waiting')), (RUNNING, _('Working')), (DONE, _('Done')), (FAILED, _('Failed'))]

    element = models.CharField(max_length=30, db_index=True)
    tier = models.CharField(max_length=10, choices=TIERS, default=STANDARD)
    status = models.CharField(max_length=10, choices=STATUSES, default=QUEUED, db_index=True)
    error = models.CharField(max_length=300, blank=True)
    person = models.JSONField(default=dict, blank=True)              # business card / signature: name, title, phone, email
    note = models.CharField(max_length=500, blank=True)              # logo: what the owner asked for
    design = models.JSONField(default=dict, blank=True)              # logo: concepts (name, idea, symbol), palette, pairing, keywords, personality
    chosen = models.PositiveSmallIntegerField(null=True, blank=True)  # logo: the concept the owner chose
    bundled = models.BooleanField(default=False)                     # made as a part of the whole kit (discounted)
    job_id = models.PositiveIntegerField(null=True, blank=True, editable=False)                # the paid job that designs it
    created_by = models.ForeignKey(settings.AUTH_USER_MODEL, null=True, blank=True, on_delete=models.SET_NULL, related_name='+', editable=False)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ['-created_at', '-id']

    @property
    def is_working(self):
        return self.status in (self.QUEUED, self.RUNNING)


class BrandFile(CompanyScopedModel):
    asset = models.ForeignKey(BrandAsset, on_delete=models.CASCADE, related_name='files')
    name = models.CharField(max_length=120)
    file = models.FileField(upload_to=upload_file, storage=private_storage)
    size = models.PositiveIntegerField(default=0)

    class Meta:
        ordering = ['name']

    @property
    def is_image(self):
        return self.name.lower().endswith(('.png', '.svg', '.jpg', '.ico'))
