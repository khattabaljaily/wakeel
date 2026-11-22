from django.conf import settings
from django.db import models
from django.utils import timezone
from django.utils.translation import gettext_lazy as _

from apps.core.tenancy import CompanyScopedModel

# An asset whose expiry is this close counts as "expiring soon" on the board, in the list and in the side menu badge.
SOON_DAYS = 30


class Asset(CompanyScopedModel):
    """A digital asset the company pays for and must renew: a domain, hosting, a software licence, a cloud account, a
    subscription or an SSL certificate. It holds what is needed to renew it on time (who provides it, when it ends, what it
    costs, who looks after it) and never a password or a key: those do not belong in this list."""

    DOMAIN, HOSTING, LICENSE, CLOUD, SUBSCRIPTION, SSL, OTHER = ('domain', 'hosting', 'license', 'cloud', 'subscription',
                                                                  'ssl', 'other')
    KINDS = [
        (DOMAIN, _('Domain')),
        (HOSTING, _('Hosting')),
        (LICENSE, _('Software licence')),
        (CLOUD, _('Cloud service account')),
        (SUBSCRIPTION, _('Subscription')),
        (SSL, _('SSL certificate')),
        (OTHER, _('Other')),
    ]
    ICONS = {DOMAIN: 'bi-globe2', HOSTING: 'bi-hdd-network', LICENSE: 'bi-key', CLOUD: 'bi-cloud', SUBSCRIPTION: 'bi-arrow-repeat',
             SSL: 'bi-shield-lock', OTHER: 'bi-box'}
    # The kinds whose end date can be read from the internet (a domain's, from its registry). The others are typed by hand.
    CHECKABLE = (DOMAIN,)

    MONTHLY, YEARLY, ONCE = 'monthly', 'yearly', 'once'
    CYCLES = [
        (YEARLY, _('Yearly')),
        (MONTHLY, _('Monthly')),
        (ONCE, _('One-time')),
    ]

    OK, FAILED = 'ok', 'failed'

    kind = models.CharField(_('type'), max_length=20, choices=KINDS, default=DOMAIN)
    name = models.CharField(_('name'), max_length=200)
    provider = models.CharField(_('provider'), max_length=200, blank=True)
    # The domain, host name or address it is about (example.com): what the automatic check looks up.
    identifier = models.CharField(_('domain or address'), max_length=255, blank=True)
    account = models.CharField(_('account it is under'), max_length=200, blank=True,
                               help_text=_('The e-mail or user name of the account, so anyone can find it. Never a password.'))
    start_date = models.DateField(_('start date'), null=True, blank=True)
    expiry_date = models.DateField(_('renewal date'), null=True, blank=True)
    auto_renew = models.BooleanField(_('renews automatically'), default=False)
    cost = models.DecimalField(_('cost'), max_digits=10, decimal_places=2, null=True, blank=True)
    currency = models.CharField(_('currency'), max_length=3, default='USD')
    cycle = models.CharField(_('billing'), max_length=10, choices=CYCLES, default=YEARLY)
    responsible = models.ForeignKey(settings.AUTH_USER_MODEL, null=True, blank=True, on_delete=models.SET_NULL,
                                    related_name='+', verbose_name=_('responsible'))
    notes = models.TextField(_('notes'), blank=True)
    # The last reminder stage sent for the current expiry date (90, 30, 7, 1 or 0 days before); cleared when it changes.
    reminded_days = models.SmallIntegerField(null=True, blank=True, editable=False)
    # The last automatic check: when, whether it read a date, and what went wrong if it did not.
    checked_at = models.DateTimeField(null=True, blank=True, editable=False)
    check_status = models.CharField(max_length=10, blank=True, editable=False)
    check_note = models.CharField(max_length=200, blank=True, editable=False)
    created_by = models.ForeignKey(settings.AUTH_USER_MODEL, null=True, blank=True, on_delete=models.SET_NULL,
                                   related_name='+', editable=False)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        ordering = ['expiry_date', 'name', 'id']
        indexes = [models.Index(fields=['company', 'expiry_date'])]

    def __str__(self):
        return self.name

    @property
    def icon(self):
        return self.ICONS.get(self.kind, 'bi-box')

    @property
    def checkable(self):
        return self.kind in self.CHECKABLE and bool(self.identifier)

    @property
    def days_left(self):
        if self.expiry_date is None:
            return None
        return (self.expiry_date - timezone.localdate()).days

    @property
    def days_overdue(self):
        """How many days late it is, or None when it is not late."""
        days = self.days_left
        return -days if days is not None and days < 0 else None

    @property
    def status(self):
        """'expired', 'soon', 'valid', or '' when no renewal date is known."""
        days = self.days_left
        if days is None:
            return ''
        return 'expired' if days < 0 else 'soon' if days <= SOON_DAYS else 'valid'

    @property
    def yearly_cost(self):
        """What it costs in a year (a monthly price times twelve); None for a one-time cost or when no cost is set."""
        if self.cost is None or self.cycle == self.ONCE:
            return None
        return self.cost * 12 if self.cycle == self.MONTHLY else self.cost
