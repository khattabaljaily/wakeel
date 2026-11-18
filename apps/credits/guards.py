"""Spend guards: the last line of defence against AI use that is not paid for.

A price covers one use. These bound what a series of uses, a bug or an attacker can cost: the platform's monthly AI budget
(the real provider cost of all companies, from the jobs), a per-company hourly limit on paid jobs, and a per-company daily limit
on refunds (a refunded job still cost us the provider bill). Superusers (admins testing) are exempt."""
import time
from datetime import timedelta
from decimal import Decimal

from django.conf import settings
from django.db.models import Sum
from django.utils import timezone

from .models import WalletTransaction

_CACHE_SECONDS = 60
_spend_cache = {'at': 0.0, 'month': None, 'value': Decimal(0)}


def _month_start(now):
    return now.replace(day=1, hour=0, minute=0, second=0, microsecond=0)


def spend_this_month_usd(force: bool = False) -> Decimal:
    """Provider cost recorded on the jobs this month, all companies (cached for a minute)."""
    from apps.jobs.models import Job
    now = timezone.now()
    month = (now.year, now.month)
    if force or _spend_cache['month'] != month or time.time() - _spend_cache['at'] > _CACHE_SECONDS:
        total = Job.objects.filter(created_at__gte=_month_start(now)).aggregate(s=Sum('cost_usd'))['s'] or Decimal(0)
        _spend_cache.update(at=time.time(), month=month, value=Decimal(total))
    return _spend_cache['value']


def reset_cache():
    _spend_cache.update(at=0.0, month=None, value=Decimal(0))


def blocked_reason(company, user, cost: int = 0) -> str | None:
    """'budget_exhausted' | 'rate_limited' | None."""
    if user is not None and user.is_superuser:
        return None
    limit = Decimal(str(settings.AI_MONTHLY_BUDGET_USD))
    if limit > 0 and spend_this_month_usd() >= limit:
        return 'budget_exhausted'
    now = timezone.now()
    charges = WalletTransaction.objects.filter(company=company, action=WalletTransaction.AI_SERVICE)
    if charges.filter(created_at__gte=now - timedelta(hours=1)).count() >= settings.AI_MAX_CHARGES_PER_HOUR:
        return 'rate_limited'
    if WalletTransaction.objects.filter(company=company, action=WalletTransaction.REFUND,
                                        created_at__gte=now - timedelta(days=1)).count() >= settings.AI_MAX_REFUNDS_PER_DAY:
        return 'rate_limited'
    return None
