from django.conf import settings
from django.db import models
from django.utils.translation import gettext_lazy as _

from apps.companies.models import Company
from apps.content.models import Post


class AdDraft(models.Model):
    """A paid promotion of a published Facebook post, suggested by the AI and created in Meta as PAUSED.

    Wakeel never starts spending: a person reviews the campaign and turns it on in Meta Ads Manager.
    """

    class Status(models.TextChoices):
        SUGGESTING = 'suggesting', _('قيد الاقتراح')
        SUGGESTED = 'suggested', _('مقترح')
        CREATED = 'created', _('أُنشئ متوقفاً في Meta')
        FAILED = 'failed', _('تعذّر')

    class Gender(models.TextChoices):
        ALL = 'all', _('الجميع')
        MALE = 'male', _('رجال')
        FEMALE = 'female', _('نساء')

    company = models.ForeignKey(Company, on_delete=models.CASCADE, related_name='ad_drafts')
    post = models.ForeignKey(Post, on_delete=models.CASCADE, related_name='ad_drafts')
    status = models.CharField(max_length=12, choices=Status.choices, default=Status.SUGGESTING)
    daily_budget = models.DecimalField(_('الميزانية اليومية'), max_digits=10, decimal_places=2, default=5)
    days = models.PositiveSmallIntegerField(_('عدد الأيام'), default=7)
    age_min = models.PositiveSmallIntegerField(_('العمر من'), default=18)
    age_max = models.PositiveSmallIntegerField(_('العمر إلى'), default=55)
    gender = models.CharField(_('الجنس'), max_length=6, choices=Gender.choices, default=Gender.ALL)
    countries = models.CharField(_('الدول'), max_length=100, blank=True, help_text=_('رموز الدول، مثل: QA SA AE'))
    rationale = models.TextField(blank=True)
    audience_notes = models.TextField(blank=True)
    campaign_id = models.CharField(max_length=40, blank=True)
    adset_id = models.CharField(max_length=40, blank=True)
    ad_id = models.CharField(max_length=40, blank=True)
    error = models.TextField(blank=True)
    created_by = models.ForeignKey(settings.AUTH_USER_MODEL, null=True, on_delete=models.SET_NULL, related_name='+')
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ['-created_at']

    def __str__(self):
        return f'{self.post} · {self.get_status_display()}'

    @property
    def total_budget(self):
        return self.daily_budget * self.days
