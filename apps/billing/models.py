from django.conf import settings
from django.db import models
from django.utils.translation import gettext_lazy as _

from apps.companies.models import Company


class Payment(models.Model):
    """One top-up bought with a card: created when the member chooses a package, paid when Stripe confirms it. The
    credit is added to the wallet exactly once, when the confirmation arrives (never when the member returns)."""

    CREATED, PAID, EXPIRED = 'created', 'paid', 'expired'
    STATUSES = [(CREATED, _('Waiting for payment')), (PAID, _('Paid')), (EXPIRED, _('Not completed'))]

    company = models.ForeignKey(Company, on_delete=models.CASCADE, related_name='payments')
    user = models.ForeignKey(settings.AUTH_USER_MODEL, null=True, blank=True, on_delete=models.SET_NULL, related_name='+')
    amount_usd = models.DecimalField(max_digits=8, decimal_places=2)
    points = models.PositiveIntegerField()
    # The operator whose gateway took this payment (enjaz-operators): only its webhook may confirm it, and it is
    # counted in that operator's monthly report.
    operator = models.CharField(max_length=20, default='banan', db_index=True)
    currency = models.CharField(max_length=3, default='USD')
    status = models.CharField(max_length=10, choices=STATUSES, default=CREATED, db_index=True)
    stripe_session_id = models.CharField(max_length=120, blank=True, db_index=True)
    created_at = models.DateTimeField(auto_now_add=True)
    paid_at = models.DateTimeField(null=True, blank=True)

    class Meta:
        ordering = ['-created_at', '-id']

    def __str__(self):
        return f'{self.company}: ${self.amount_usd} {self.status}'
