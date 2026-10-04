from django.db import models
from django.utils.translation import gettext_lazy as _

from apps.companies.models import Company
from apps.content.models import Post


class PostInsight(models.Model):
    """How one published post performed on one platform, as last read from the platform."""

    post = models.ForeignKey(Post, on_delete=models.CASCADE, related_name='insights')
    platform = models.CharField(max_length=10)
    reach = models.PositiveIntegerField(null=True, blank=True, help_text='People who saw it; null when the platform did not say.')
    likes = models.PositiveIntegerField(default=0)
    comments = models.PositiveIntegerField(default=0)
    shares = models.PositiveIntegerField(default=0)
    saves = models.PositiveIntegerField(default=0)
    fetched_at = models.DateTimeField(auto_now=True)

    class Meta:
        constraints = [models.UniqueConstraint(fields=['post', 'platform'], name='one_insight_per_post_platform')]

    def __str__(self):
        return f'{self.post_id} · {self.platform}'

    @property
    def engagement(self):
        return self.likes + self.comments + self.shares + self.saves

    @property
    def rate(self):
        """Engagement as a percentage of reach, or None without reach."""
        return round(self.engagement * 100 / self.reach, 2) if self.reach else None


class MonthlyReport(models.Model):
    """A month's results for a company, with the AI's reading of them. Shareable by a secret link."""

    class Status(models.TextChoices):
        GENERATING = 'generating', _('قيد الإعداد')
        READY = 'ready', _('جاهز')
        FAILED = 'failed', _('تعذّر الإعداد')

    company = models.ForeignKey(Company, on_delete=models.CASCADE, related_name='reports')
    month = models.DateField(help_text='First day of the month the report covers.')
    status = models.CharField(max_length=12, choices=Status.choices, default=Status.GENERATING)
    stats = models.JSONField(default=dict, blank=True)
    summary = models.TextField(blank=True)
    wins = models.JSONField(default=list, blank=True)
    recommendations = models.JSONField(default=list, blank=True)
    error = models.TextField(blank=True)
    share_token = models.CharField(max_length=64, blank=True, db_index=True)
    emailed_at = models.DateTimeField(null=True, blank=True)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ['-month']
        constraints = [models.UniqueConstraint(fields=['company', 'month'], name='one_report_per_month')]

    def __str__(self):
        return f'{self.company} · {self.month:%Y-%m}'


class Competitor(models.Model):
    """A competitor the brand watches. Wakeel reads its website; the team can paste its recent posts."""

    company = models.ForeignKey(Company, on_delete=models.CASCADE, related_name='competitor_list')
    name = models.CharField(_('الاسم'), max_length=150)
    website = models.CharField(_('الموقع الإلكتروني'), max_length=300, blank=True)
    social = models.CharField(_('حسابات التواصل'), max_length=500, blank=True, help_text=_('روابط أو أسماء حسابات، مفصولة بمسافات.'))
    sample_posts = models.TextField(_('أمثلة من منشوراتهم'), blank=True,
                                    help_text=_('الصق نصوص منشورات حديثة لهم أو صف ما ينشرونه؛ يقرأها وكيل في التحليل.'))
    site_text = models.TextField(blank=True)
    site_read_at = models.DateTimeField(null=True, blank=True)
    site_error = models.CharField(max_length=300, blank=True)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ['name']

    def __str__(self):
        return self.name


class CompetitorAnalysis(models.Model):
    """The AI's reading of the competitors: what they do, and the gaps and openings for the brand."""

    class Status(models.TextChoices):
        GENERATING = 'generating', _('قيد التحليل')
        READY = 'ready', _('جاهز')
        FAILED = 'failed', _('تعذّر التحليل')

    company = models.ForeignKey(Company, on_delete=models.CASCADE, related_name='competitor_analyses')
    status = models.CharField(max_length=12, choices=Status.choices, default=Status.GENERATING)
    summary = models.TextField(blank=True)
    competitors = models.JSONField(default=list, blank=True)  # [{name, positioning, themes, strengths, weaknesses}]
    gaps = models.JSONField(default=list, blank=True)
    opportunities = models.JSONField(default=list, blank=True)
    error = models.TextField(blank=True)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ['-created_at']
