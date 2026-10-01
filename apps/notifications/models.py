from django.conf import settings
from django.db import models
from django.utils.translation import gettext_lazy as _

from apps.companies.models import Company


class Notification(models.Model):
    """Something a team member should know about: a post waiting for review, a plan that is ready, a comment…"""

    user = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.CASCADE, related_name='notifications')
    company = models.ForeignKey(Company, on_delete=models.CASCADE, related_name='notifications')
    icon = models.CharField(max_length=40, default='bi-bell')
    message = models.CharField(max_length=300)
    url = models.CharField(max_length=300, blank=True)
    created_at = models.DateTimeField(auto_now_add=True)
    read_at = models.DateTimeField(null=True, blank=True)

    class Meta:
        verbose_name = _('إشعار')
        verbose_name_plural = _('الإشعارات')
        ordering = ['-created_at']
        indexes = [models.Index(fields=['user', 'read_at'])]

    def __str__(self):
        return self.message


class PushSubscription(models.Model):
    """A browser/device that agreed to receive push notifications for a user (Web Push)."""

    user = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.CASCADE, related_name='push_subscriptions')
    endpoint = models.TextField()
    # Endpoints can be long; uniqueness is kept on their SHA-256 (MySQL can't index long text).
    endpoint_hash = models.CharField(max_length=64, unique=True)
    p256dh = models.CharField(max_length=200)
    auth = models.CharField(max_length=100)
    user_agent = models.CharField(max_length=300, blank=True)
    created_at = models.DateTimeField(auto_now_add=True)
    last_sent_at = models.DateTimeField(null=True, blank=True)

    def __str__(self):
        return f'{self.user} · {self.user_agent[:40]}'

    @staticmethod
    def hash(endpoint):
        import hashlib
        return hashlib.sha256(endpoint.encode()).hexdigest()

    def as_info(self):
        return {'endpoint': self.endpoint, 'keys': {'p256dh': self.p256dh, 'auth': self.auth}}
