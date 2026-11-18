"""Tell team members about things that need them, in the app and (for the important ones) by email."""
import logging

from django.conf import settings
from django.core.mail import send_mail
from django.template.loader import render_to_string
from django.utils import translation
from django.utils.translation import gettext_lazy as _

from apps.companies.models import Membership

from . import push
from .models import Notification

logger = logging.getLogger(__name__)


def managers(company):
    return [m.user for m in company.memberships.select_related('user')
            .filter(role__in=[Membership.Role.OWNER, Membership.Role.ADMIN])]


def members(company, users):
    """Keep only the users who still belong to the company (a post's author may have left)."""
    ids = set(company.memberships.values_list('user_id', flat=True))
    return [u for u in users if u is not None and u.pk in ids]


def notify(users, company, message, url='', *, icon='bi-bell', actor=None, email=False):
    """Create an in-app notification for each user (never the actor), and optionally email it."""
    seen, recipients = set(), []
    for user in users:
        if user is None or user.pk in seen or (actor is not None and user.pk == actor.pk):
            continue
        seen.add(user.pk)
        recipients.append(user)
    # `message` may be lazy (gettext_lazy / format_lazy): each recipient reads it in their own language.
    for user in recipients:
        with translation.override(user.language or settings.LANGUAGE_CODE):
            text = str(message)[:300]
            Notification.objects.create(user=user, company=company, message=text, url=url, icon=icon)
            push.send([user], title=company.name, body=text, url=url, tag=f'wakeel-{company.pk}')
            if email and user.email and user.email_notifications:
                _email(user, company, text, url)
    return recipients


def _email(user, company, message, url):
    context = {'user': user, 'company': company, 'message': message,
               'link': settings.SITE_URL + url if url.startswith('/') else url}
    try:
        send_mail(_('%(company)s · وكيل') % {'company': company.name}, render_to_string('notifications/emails/notification.txt', context),
                  None, [user.email])
    except Exception:  # an email outage must never break the action that triggered it
        logger.exception('Could not email notification to user %s', user.pk)


def who(user):
    """How a person is named in a sentence."""
    return user.first_name or user.email


def notify_event(users, kind, *, company, url='', dedupe_key='', actor=None, email=False, **values):
    """Notify one person or several of a kind of event (registry.KINDS). With a `dedupe_key` a person already told that
    thing is not told again. Never raises: a notification must not break the action it describes (same rule as the
    activity log). Returns how many notifications were made."""
    from .registry import KINDS
    assert kind in KINDS, kind
    if hasattr(users, 'pk'):
        users = [users]
    made = 0
    for user in users:
        try:
            if user is None or (actor is not None and user.pk == actor.pk):
                continue
            if dedupe_key and Notification.objects.filter(user=user, dedupe_key=dedupe_key).exists():
                continue
            note = Notification.objects.create(user=user, company=company, kind=kind, params=values, url=url,
                                               dedupe_key=dedupe_key, icon=KINDS[kind][0])
            made += 1
            with translation.override(user.language or settings.LANGUAGE_CODE):
                text = note.text[:300]
                push.send([user], title=company.name, body=text, url=url, tag=f'wakeel-{company.pk}')
                if email and user.email and user.email_notifications:
                    _email(user, company, text, url)
        except Exception:
            logger.exception('Could not make the notification %s for user %s', kind, getattr(user, 'pk', user))
    return made


def notify_managers_event(company, kind, *, exclude=None, **kwargs):
    """Notify the owner and the administrators of a company (not `exclude`, the person who caused it)."""
    return notify_event(managers(company), kind, company=company, actor=exclude, **kwargs)


def mark_read_for(user, url):
    """The person opened the thing a notification points to: its notifications are read."""
    from django.utils import timezone
    Notification.objects.filter(user=user, url=url, read_at__isnull=True).update(read_at=timezone.now())


def prune(now=None):
    """Delete old notifications (all companies): read ones after `NOTIFICATION_KEEP_READ_DAYS` days, and the ones nobody
    ever read after `NOTIFICATION_KEEP_UNREAD_DAYS`. What made them does not make them again: every maker keeps its own
    record of what it already told. Returns how many were deleted."""
    from datetime import timedelta

    from django.db.models import Q
    from django.utils import timezone
    now = now or timezone.now()
    read_before = now - timedelta(days=settings.NOTIFICATION_KEEP_READ_DAYS)
    unread_before = now - timedelta(days=settings.NOTIFICATION_KEEP_UNREAD_DAYS)
    deleted, _by_model = Notification.objects.filter(
        Q(read_at__isnull=False, read_at__lt=read_before) | Q(read_at__isnull=True, created_at__lt=unread_before)).delete()
    return deleted
