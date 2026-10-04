from django.conf import settings
from django.db import models
from django.utils.translation import gettext_lazy as _

from apps.companies.models import Company
from apps.content.models import Post


class InboxItem(models.Model):
    """A comment left on one of the company's published posts, with the AI's reading and a suggested reply."""

    class Status(models.TextChoices):
        NEW = 'new', _('جديد')
        REPLIED = 'replied', _('تم الرد')
        DISMISSED = 'dismissed', _('مُتجاهَل')

    class Sentiment(models.TextChoices):
        POSITIVE = 'positive', _('إيجابي')
        NEUTRAL = 'neutral', _('محايد')
        NEGATIVE = 'negative', _('سلبي')

    class Category(models.TextChoices):
        QUESTION = 'question', _('سؤال')
        COMPLAINT = 'complaint', _('شكوى')
        PRAISE = 'praise', _('إشادة')
        SPAM = 'spam', _('مزعج')
        OTHER = 'other', _('أخرى')

    class Urgency(models.TextChoices):
        LOW = 'low', _('منخفض')
        NORMAL = 'normal', _('عادي')
        HIGH = 'high', _('عاجل')
        CRISIS = 'crisis', _('أزمة')

    company = models.ForeignKey(Company, on_delete=models.CASCADE, related_name='inbox_items')
    post = models.ForeignKey(Post, null=True, blank=True, on_delete=models.SET_NULL, related_name='inbox_items')
    platform = models.CharField(max_length=10)
    external_id = models.CharField(max_length=100)
    author = models.CharField(max_length=150, blank=True)
    text = models.TextField(blank=True)
    received_at = models.DateTimeField()

    triaged = models.BooleanField(default=False)
    sentiment = models.CharField(max_length=10, choices=Sentiment.choices, blank=True)
    category = models.CharField(max_length=10, choices=Category.choices, blank=True)
    urgency = models.CharField(max_length=10, choices=Urgency.choices, blank=True)
    suggested_reply = models.TextField(blank=True)

    status = models.CharField(max_length=10, choices=Status.choices, default=Status.NEW)
    reply_text = models.TextField(blank=True)
    reply_error = models.CharField(max_length=300, blank=True)
    replied_at = models.DateTimeField(null=True, blank=True)
    replied_by = models.ForeignKey(settings.AUTH_USER_MODEL, null=True, blank=True, on_delete=models.SET_NULL, related_name='+')
    auto_replied = models.BooleanField(default=False)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ['-received_at']
        constraints = [models.UniqueConstraint(fields=['company', 'platform', 'external_id'], name='one_inbox_item_per_comment')]
        indexes = [models.Index(fields=['company', 'status'])]

    def __str__(self):
        return f'{self.author}: {self.text[:40]}'

    @property
    def is_alarming(self):
        return self.urgency in (self.Urgency.HIGH, self.Urgency.CRISIS)
