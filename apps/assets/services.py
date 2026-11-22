import calendar
import datetime

from django.utils import timezone

from .models import Asset, RenewalLog


class CannotRenew(Exception):
    """The asset has no renewal date, or it is a one-time cost, so there is nothing to renew."""


def add_months(day, months):
    """The same day `months` later (the last day of the month when it does not exist there: 31 Jan + 1 month = 28/29 Feb)."""
    index = day.year * 12 + day.month - 1 + months
    year, month = divmod(index, 12)
    month += 1
    return datetime.date(year, month, min(day.day, calendar.monthrange(year, month)[1]))


def next_date(asset, today=None):
    """The renewal date after this one: a cycle later, and when the asset is already late, the first date that is not in the past."""
    today = today or timezone.localdate()
    if asset.expiry_date is None or asset.cycle == Asset.ONCE:
        raise CannotRenew
    step = 12 if asset.cycle == Asset.YEARLY else 1
    new = add_months(asset.expiry_date, step)
    for _ in range(1200):                      # a monthly asset that was forgotten for years still ends up in the future
        if new >= today:
            return new
        new = add_months(new, step)
    return new


def renew(asset, user=None, today=None):
    """Mark the asset renewed: its date moves one cycle on, its reminders start again, and the renewal is logged."""
    today = today or timezone.localdate()
    new = next_date(asset, today)
    log = RenewalLog.all_companies.create(company=asset.company, asset=asset, renewed_on=today, old_expiry=asset.expiry_date,
                                          new_expiry=new, cost=asset.cost, currency=asset.currency, by=user)
    Asset.all_companies.filter(pk=asset.pk).update(expiry_date=new, reminded_days=None)
    asset.expiry_date, asset.reminded_days = new, None
    return log
