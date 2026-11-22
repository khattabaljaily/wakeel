"""Renewal reminders for digital assets: 90, 30, 7 and 1 day before the renewal date, and on the day (or after). Each stage is
sent once per renewal date; a new date (a renewal) starts the stages again. The owners and administrators of the company
receive it, and so does the member responsible for the asset, in their language, in the notification centre and by e-mail.
Run it once a day (`manage.py send_asset_reminders`, from cron): it first reads again the end date of every domain it can, so
a renewal done elsewhere is seen."""
import datetime
from collections import defaultdict

from django.urls import reverse
from django.utils import timezone

from apps.notifications.services import managers, notify_event

from . import checks
from .models import Asset

STAGES = (90, 30, 7, 1, 0)


def stage(asset, today):
    """The reminder stage the asset has reached today, or None when it is not due yet."""
    days = (asset.expiry_date - today).days
    reached = [s for s in STAGES if days <= s]
    return min(reached) if reached else None


def due(today=None):
    """{company: [(asset, stage)]} for every asset whose current stage has not been sent yet."""
    today = today or timezone.localdate()
    found = defaultdict(list)
    candidates = Asset.all_companies.filter(expiry_date__isnull=False,
                                            expiry_date__lte=today + datetime.timedelta(days=max(STAGES)))
    for asset in candidates.select_related('company', 'responsible').order_by('expiry_date'):
        now = stage(asset, today)
        if now is not None and (asset.reminded_days is None or now < asset.reminded_days):
            found[asset.company].append((asset, now))
    return found


def refresh():
    """Read again the end date of every domain that has an address. Returns how many were read."""
    read = 0
    for asset in Asset.all_companies.filter(kind__in=Asset.CHECKABLE).exclude(identifier=''):
        read += bool(checks.run(asset))
    return read


def send_due(today=None):
    """Send what is due. Returns the number of notifications made. A stage is marked as sent only when somebody was told,
    so a failure is retried the next day."""
    today = today or timezone.localdate()
    url = reverse('assets:list') + '?status=soon'
    made = 0
    for company, items in due(today).items():
        managing = list(managers(company))
        delivered = 0
        for asset, now in items:
            expired = asset.expiry_date < today
            people = managing + ([asset.responsible] if asset.responsible and asset.responsible.is_active else [])
            delivered += notify_event(people, 'expired' if expired else 'expiring', company=company, url=url, email=True,
                                      title=asset.name, date=f'⁦{asset.expiry_date:%Y-%m-%d}⁩',
                                      dedupe_key=f'asset:{asset.pk}:{asset.expiry_date}:{now}')
        made += delivered
        if delivered or not managing:
            for asset, now in items:
                Asset.all_companies.filter(pk=asset.pk).update(reminded_days=now)
    return made
