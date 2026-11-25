from django.db import models
from django.utils.translation import gettext_lazy as _


class ExchangeRate(models.Model):
    """How many units of a currency one US dollar buys, as last set. Pegged currencies never need a row (see
    currencies.PEGS). A manual rate is the owner's, for currencies whose market rate the free sources do not follow
    (Sudan): it holds until `manual_until`, and the automatic update leaves it alone until then."""

    API, MANUAL = 'api', 'manual'
    SOURCES = [(API, _('Automatic')), (MANUAL, _('Set by hand'))]

    currency = models.CharField(max_length=3, primary_key=True)
    per_usd = models.DecimalField(max_digits=24, decimal_places=10)
    source = models.CharField(max_length=10, choices=SOURCES, default=API)
    note = models.CharField(max_length=200, blank=True)                   # where a manual rate came from
    manual_until = models.DateTimeField(null=True, blank=True)
    updated_at = models.DateTimeField()

    def __str__(self):
        return f'1 USD = {self.per_usd} {self.currency} ({self.source})'


class RateLog(models.Model):
    """Every rate ever set, so the rate behind any past price or payment can be shown."""

    currency = models.CharField(max_length=3, db_index=True)
    per_usd = models.DecimalField(max_digits=24, decimal_places=10)
    source = models.CharField(max_length=10)
    note = models.CharField(max_length=200, blank=True)
    at = models.DateTimeField(db_index=True)

    class Meta:
        ordering = ['-at', '-id']
