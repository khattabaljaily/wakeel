from django.conf import settings
from django.db import models
from django.utils.translation import gettext_lazy as _

from apps.companies.models import Company


class SocialAccount(models.Model):
    """A publishing destination: a Facebook Page or its Instagram account (through Meta), or a TikTok account."""

    class Platform(models.TextChoices):
        FACEBOOK = 'facebook', _('فيسبوك')
        INSTAGRAM = 'instagram', _('إنستغرام')
        TIKTOK = 'tiktok', _('تيك توك')

    company = models.ForeignKey(Company, on_delete=models.CASCADE, related_name='social_accounts')
    platform = models.CharField(max_length=10, choices=Platform.choices)
    external_id = models.CharField(max_length=64, help_text='Page ID, Instagram professional account ID, or TikTok open_id.')
    name = models.CharField(max_length=200)
    # The Page access token; the Instagram account is reached through its Page's token too.
    access_token = models.TextField()
    # TikTok tokens last a day and are renewed with the refresh token (valid a year); Meta Page tokens don't expire.
    refresh_token = models.TextField(blank=True)
    # Facebook only: the long-lived user token (about 60 days), needed to reach the user's ad accounts.
    user_token = models.TextField(blank=True)
    token_expires_at = models.DateTimeField(null=True, blank=True)
    # Meta (Facebook/Instagram) only: the app-scoped id of the person who connected it, so Meta's deauthorize and
    # data-deletion callbacks, which name only that user, can find the accounts to remove.
    meta_user_id = models.CharField(max_length=64, blank=True, db_index=True)
    last_error = models.TextField(blank=True)
    connected_by = models.ForeignKey(settings.AUTH_USER_MODEL, null=True, on_delete=models.SET_NULL, related_name='+')
    connected_at = models.DateTimeField(auto_now=True)

    class Meta:
        verbose_name = _('حساب تواصل')
        verbose_name_plural = _('حسابات التواصل')
        constraints = [models.UniqueConstraint(fields=['company', 'platform'], name='one_account_per_platform')]

    def __str__(self):
        return f'{self.get_platform_display()}: {self.name}'


class MetaDeletionRequest(models.Model):
    """A data-deletion request received from Meta; its code lets the person check the status page Meta links to."""

    code = models.CharField(max_length=32, unique=True)
    meta_user_id = models.CharField(max_length=64)
    accounts_deleted = models.PositiveIntegerField(default=0)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        verbose_name = _('طلب حذف بيانات من Meta')
        verbose_name_plural = _('طلبات حذف البيانات من Meta')
        ordering = ['-created_at']

    def __str__(self):
        return self.code
