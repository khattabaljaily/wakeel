from django.conf import settings
from django.db import models
from django.utils.translation import gettext_lazy as _

from apps.companies.models import Company


class Wallet(models.Model):
    """One prepaid balance per company, in points (1 point = 0.001 riyal; the riyal is the base currency)."""

    company = models.OneToOneField(Company, on_delete=models.CASCADE, related_name='wallet')
    balance = models.IntegerField(_('balance'), default=0)
    is_exempt = models.BooleanField(_('exempt'), default=False, help_text=_('Never charged (internal and demo companies).'))

    def __str__(self):
        return f'{self.company}: {self.balance} pts'


class WalletTransaction(models.Model):
    """One line of the wallet's ledger. A charge keeps its itemised `breakdown` (what the price was made of), so the
    customer can see why a deduction is what it is."""

    TOPUP, AI_SERVICE, REFUND, ADMIN_GRANT, TRIAL = 'topup', 'ai_service', 'refund', 'admin_grant', 'trial_grant'
    ACTION_CHOICES = [
        (TOPUP, _('Top-up')), (AI_SERVICE, _('AI service')), (REFUND, _('Refund')),
        (ADMIN_GRANT, _('Admin grant')), (TRIAL, _('Free trial credit')),
    ]

    company = models.ForeignKey(Company, on_delete=models.CASCADE, related_name='wallet_transactions')
    user = models.ForeignKey(settings.AUTH_USER_MODEL, null=True, blank=True, on_delete=models.SET_NULL, related_name='+')
    delta = models.IntegerField(_('points'))
    action = models.CharField(max_length=20, choices=ACTION_CHOICES)
    service_key = models.CharField(max_length=40, blank=True)
    units = models.PositiveIntegerField(null=True, blank=True)
    breakdown = models.JSONField(default=list, blank=True)       # [{"key": ..., "points": ...}]: the itemised price
    reference = models.CharField(max_length=60, blank=True)      # what it paid for: "job:123"
    description = models.TextField(blank=True)
    refund_of = models.OneToOneField('self', null=True, blank=True, on_delete=models.SET_NULL, related_name='refund')
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ['-created_at', '-id']
        indexes = [models.Index(fields=['company', 'created_at'])]

    def __str__(self):
        return f'{self.company}: {self.delta:+d} ({self.action})'
