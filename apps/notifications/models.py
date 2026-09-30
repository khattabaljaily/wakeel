from django.conf import settings
from django.db import models

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
        verbose_name = 'إشعار'
        verbose_name_plural = 'الإشعارات'
        ordering = ['-created_at']
        indexes = [models.Index(fields=['user', 'read_at'])]

    def __str__(self):
        return self.message
