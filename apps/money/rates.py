"""The rate of a currency against the dollar and the conversions built on it. Wakeel's costs and price list are in
dollars; a company sees and pays its own currency, converted at the rate of the moment, to the currency's smallest unit.

Where a rate comes from, in order: 1 for the dollar; the official peg (currencies.PEGS); a rate set by hand while it
holds; the daily automatic rate while it is fresh. With none of them the currency has no rate (RateUnavailable) and
nothing is sold in it until one is set: a price is never shown at a rate nobody trusts."""
from datetime import timedelta
from decimal import Decimal

from django.db import transaction
from django.utils import timezone

from . import currencies
from .models import ExchangeRate, RateLog

POINTS_PER_DOLLAR = 1000
# The sources publish once a day; a day and a half covers one missed update.
AUTO_MAX_AGE = timedelta(hours=36)
# Two sources further apart than this do not settle a rate on their own.
AGREEMENT = Decimal('0.03')
# A single source that moves a rate by more than this since the last one is not believed on its own.
SINGLE_SOURCE_JUMP = Decimal('0.10')


class RateUnavailable(Exception):
    """No trusted rate for the currency right now."""


class Rate:
    """A rate as used for one price or payment: kept on the payment, so the amount can be traced to it."""

    def __init__(self, currency, per_usd, source, at):
        self.currency, self.per_usd, self.source, self.at = currency, Decimal(per_usd), source, at

    def from_usd(self, amount_usd):
        return currencies.quantize(Decimal(str(amount_usd)) * self.per_usd, self.currency)

    def from_points(self, points):
        return self.from_usd(Decimal(int(points or 0)) / POINTS_PER_DOLLAR)

    def __repr__(self):
        return f'<Rate 1 USD = {self.per_usd} {self.currency} ({self.source})>'


def get(currency, now=None):
    """The rate to use now. RateUnavailable when there is none to trust."""
    currency = (currency or currencies.USD).upper()
    now = now or timezone.now()
    if currency == currencies.USD:
        return Rate(currency, 1, 'usd', now)
    if currency in currencies.PEGS:
        return Rate(currency, currencies.PEGS[currency], 'peg', now)
    row = ExchangeRate.objects.filter(currency=currency).first()
    if row is None:
        raise RateUnavailable(currency)
    if row.source == ExchangeRate.MANUAL:
        if row.manual_until and row.manual_until > now:
            return Rate(currency, row.per_usd, 'manual', row.updated_at)
        raise RateUnavailable(currency)
    if now - row.updated_at > AUTO_MAX_AGE:
        raise RateUnavailable(currency)
    return Rate(currency, row.per_usd, 'api', row.updated_at)


def available(currency):
    try:
        get(currency)
        return True
    except RateUnavailable:
        return False


@transaction.atomic
def set_manual(currency, per_usd, hours, note=''):
    """The owner's rate for `hours` hours; then the currency waits for a new one (or the automatic rate, if fresh)."""
    currency, per_usd, now = currency.upper(), Decimal(str(per_usd)), timezone.now()
    if per_usd <= 0 or not currencies.is_known(currency) or currency in currencies.PEGS or currency == currencies.USD:
        raise ValueError(currency)
    ExchangeRate.objects.update_or_create(currency=currency, defaults={
        'per_usd': per_usd, 'source': ExchangeRate.MANUAL, 'note': note[:200],
        'manual_until': now + timedelta(hours=hours), 'updated_at': now})
    RateLog.objects.create(currency=currency, per_usd=per_usd, source=ExchangeRate.MANUAL, note=note[:200], at=now)


def settle(found, now=None):
    """Store the automatic rates from {source: {currency: per_usd}}. A currency is updated when two sources agree within
    AGREEMENT (the first source's figure is kept), or when only one source has it and it moved less than
    SINGLE_SOURCE_JUMP from the stored rate. Manual rates still in force, pegs and the dollar are left alone.
    Returns (updated, disputed): disputed currencies keep their old rate until it goes stale."""
    now = now or timezone.now()
    names = list(found)
    codes = set().union(*(found[n] for n in names)) if names else set()
    stored = {r.currency: r for r in ExchangeRate.objects.all()}
    updated, disputed = [], []
    for code in sorted(codes):
        if code == currencies.USD or code in currencies.PEGS or not currencies.is_known(code):
            continue
        row = stored.get(code)
        if row and row.source == ExchangeRate.MANUAL and row.manual_until and row.manual_until > now:
            continue
        figures = [found[n][code] for n in names if code in found[n]]
        first = figures[0]
        if len(figures) > 1:
            trusted = all(abs(f - first) / first <= AGREEMENT for f in figures[1:])
        else:
            trusted = row is None or row.source == ExchangeRate.MANUAL or abs(first - row.per_usd) / row.per_usd <= SINGLE_SOURCE_JUMP
        if not trusted:
            disputed.append(code)
            continue
        with transaction.atomic():
            ExchangeRate.objects.update_or_create(currency=code, defaults={
                'per_usd': first, 'source': ExchangeRate.API, 'note': ', '.join(n for n in names if code in found[n]),
                'manual_until': None, 'updated_at': now})
            if row is None or row.per_usd != first or row.source != ExchangeRate.API:
                RateLog.objects.create(currency=code, per_usd=first, source=ExchangeRate.API, at=now)
        updated.append(code)
    return updated, disputed
