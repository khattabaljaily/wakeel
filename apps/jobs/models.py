from django.conf import settings
from django.db import models
from django.utils.translation import gettext_lazy as _

from apps.companies.models import Company


class Job(models.Model):
    """A slow task (AI generation, image rendering) run by `manage.py run_worker`.

    The page that queued it polls /api/jobs/<id>/ until it's done.
    """

    class Kind(models.TextChoices):
        GENERATE_PLAN = 'generate_plan', _('إعداد خطة المحتوى')
        REWRITE_POST = 'rewrite_post', _('إعادة كتابة منشور')
        RENDER_POST = 'render_post', _('تصميم صورة منشور')
        RENDER_PLAN = 'render_plan', _('تصميم صور الخطة')
        PUBLISH_POST = 'publish_post', _('نشر منشور')
        LEARN = 'learn', _('التعلّم من الملاحظات')
        FETCH_INSIGHTS = 'fetch_insights', _('تحديث أرقام الأداء')
        GENERATE_REPORT = 'generate_report', _('إعداد تقرير الأداء')
        VARIANT_POST = 'variant_post', _('نسخة بلغة أو لهجة أخرى')
        REPOST = 'repost', _('إعادة نشر محتوى دائم')
        ANALYZE_COMPETITORS = 'competitors', _('تحليل المنافسين')
        FETCH_INBOX = 'fetch_inbox', _('قراءة التعليقات')
        AD_SUGGEST = 'ad_suggest', _('اقتراح ترويج')

    class Status(models.TextChoices):
        PENDING = 'pending', _('في الانتظار')
        RUNNING = 'running', _('قيد التنفيذ')
        DONE = 'done', _('اكتمل')
        FAILED = 'failed', _('فشل')
        CANCELLED = 'cancelled', _('أُلغي')

    company = models.ForeignKey(Company, on_delete=models.CASCADE, related_name='jobs')
    kind = models.CharField(max_length=20, choices=Kind.choices)
    params = models.JSONField(default=dict)
    status = models.CharField(max_length=10, choices=Status.choices, default=Status.PENDING)
    progress = models.PositiveSmallIntegerField(default=0)
    message = models.CharField(max_length=255, blank=True)
    error = models.TextField(blank=True)  # shown to the subscriber
    error_detail = models.TextField(blank=True)  # technical cause, for the system admin panel only
    # AI token usage, tracked per job so AI cost per company can be priced later.
    input_tokens = models.PositiveIntegerField(default=0)  # cache hits included
    output_tokens = models.PositiveIntegerField(default=0)
    cache_hit_tokens = models.PositiveIntegerField(default=0)
    model = models.CharField(max_length=80, blank=True)
    # Worked out per call (prices vary with the model, the cache and the time of day); null = prices unknown.
    cost_usd = models.DecimalField(max_digits=10, decimal_places=6, null=True, blank=True)
    created_by = models.ForeignKey(settings.AUTH_USER_MODEL, null=True, on_delete=models.SET_NULL)
    created_at = models.DateTimeField(auto_now_add=True)
    started_at = models.DateTimeField(null=True, blank=True)
    finished_at = models.DateTimeField(null=True, blank=True)

    class Meta:
        ordering = ['created_at']
        indexes = [models.Index(fields=['status', 'created_at'])]

    def __str__(self):
        return f'{self.get_kind_display()} #{self.pk} ({self.status})'

    @classmethod
    def enqueue(cls, company, kind, user=None, **params):
        return cls.objects.create(company=company, kind=kind, params=params, created_by=user)

    def set_progress(self, progress, message=''):
        self.progress = progress
        self.message = message[:255]
        self.save(update_fields=['progress', 'message'])

    def add_usage(self, result):
        from decimal import Decimal

        from django.utils import timezone

        from apps.ai.pricing import cost

        self.input_tokens += result.input_tokens
        self.output_tokens += result.output_tokens
        self.cache_hit_tokens += result.cache_hit_tokens
        self.model = result.model or self.model
        call_cost = cost(result.model, result.input_tokens, result.cache_hit_tokens, result.output_tokens, timezone.now())
        if call_cost is not None:
            self.cost_usd = (self.cost_usd or 0) + Decimal(str(round(call_cost, 6)))
        self.save(update_fields=['input_tokens', 'output_tokens', 'cache_hit_tokens', 'model', 'cost_usd'])

    @property
    def is_finished(self):
        return self.status in (self.Status.DONE, self.Status.FAILED, self.Status.CANCELLED)

    def was_cancelled(self):
        """Checked by long handlers: the user may cancel while an AI call is in flight."""
        return Job.objects.filter(pk=self.pk, status=self.Status.CANCELLED).exists()
