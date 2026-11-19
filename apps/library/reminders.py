"""Renewal reminders: 90, 30, 7 and 1 day before a document expires, and on the day (or after) it expires. Each stage is
sent once per expiry date; a new expiry date (a renewal) starts the stages again. Run it once a day
(`manage.py send_expiry_reminders`, from cron). Owners and administrators receive it, in their language, in the
notification centre and by e-mail."""
import datetime
from collections import defaultdict

from django.urls import reverse
from django.utils import timezone

from apps.notifications.services import managers, notify_event

from .models import Record

STAGES = (90, 30, 7, 1, 0)


def stage(record, today):
    """The reminder stage the record has reached today, or None when it is not due yet."""
    days = (record.expiry_date - today).days
    reached = [s for s in STAGES if days <= s]
    return min(reached) if reached else None


def due(today=None):
    """{company: [(record, stage)]} for every record whose current stage has not been sent yet."""
    today = today or timezone.localdate()
    found = defaultdict(list)
    candidates = Record.all_companies.filter(expiry_date__isnull=False,
                                             expiry_date__lte=today + datetime.timedelta(days=max(STAGES)))
    for record in candidates.select_related('company').order_by('expiry_date'):
        now = stage(record, today)
        if now is not None and (record.reminded_days is None or now < record.reminded_days):
            found[record.company].append((record, now))
    return found


def send_due(today=None):
    """Send what is due. Returns the number of notifications made. A stage is marked as sent only when somebody was told,
    so a failure is retried the next day."""
    today = today or timezone.localdate()
    url = reverse('library:list') + '?status=soon'
    made = 0
    for company, items in due(today).items():
        people = list(managers(company))
        delivered = 0
        for record, now in items:
            expired = record.expiry_date < today
            delivered += notify_event(people, 'expired' if expired else 'expiring', company=company, url=url, email=True,
                                      title=record.title, date=f'⁦{record.expiry_date:%Y-%m-%d}⁩',
                                      dedupe_key=f'record:{record.pk}:{record.expiry_date}:{now}')
        made += delivered
        if delivered or not people:
            for record, now in items:
                Record.all_companies.filter(pk=record.pk).update(reminded_days=now)
    return made
