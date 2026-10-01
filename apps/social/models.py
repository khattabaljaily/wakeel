from django.conf import settings
from django.db import models
from django.utils.translation import gettext_lazy as _

from apps.companies.models import Company


class SocialAccount(models.Model):
    """A publishing destination connected through Meta: a Facebook Page or the Instagram account linked to it."""

    class Platform(models.TextChoices):
        FACEBOOK = 'facebook', _('فيسبوك')
        INSTAGRAM = 'instagram', _('إنستغرام')

    company = models.ForeignKey(Company, on_delete=models.CASCADE, related_name='social_accounts')
    platform = models.CharField(max_length=10, choices=Platform.choices)
    external_id = models.CharField(max_length=64, help_text='Page ID, or Instagram professional account ID.')
    name = models.CharField(max_length=200)
    # The Page access token; the Instagram account is reached through its Page's token too.
    access_token = models.TextField()
    last_error = models.TextField(blank=True)
    connected_by = models.ForeignKey(settings.AUTH_USER_MODEL, null=True, on_delete=models.SET_NULL, related_name='+')
    connected_at = models.DateTimeField(auto_now=True)

    class Meta:
        verbose_name = _('حساب تواصل')
        verbose_name_plural = _('حسابات التواصل')
        constraints = [models.UniqueConstraint(fields=['company', 'platform'], name='one_account_per_platform')]

    def __str__(self):
        return f'{self.get_platform_display()}: {self.name}'
