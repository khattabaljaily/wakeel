"""Tell team members about things that need them, in the app and (for the important ones) by email."""
import logging

from django.conf import settings
from django.core.mail import send_mail
from django.template.loader import render_to_string

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
    Notification.objects.bulk_create([
        Notification(user=u, company=company, message=message[:300], url=url, icon=icon) for u in recipients
    ])
    push.send(recipients, title=company.name, body=message, url=url, tag=f'wakeel-{company.pk}')
    if email:
        for user in recipients:
            if user.email and user.email_notifications:
                _email(user, company, message, url)
    return recipients


def _email(user, company, message, url):
    context = {'user': user, 'company': company, 'message': message,
               'link': settings.SITE_URL + url if url.startswith('/') else url}
    try:
        send_mail(f'{company.name} · وكيل', render_to_string('notifications/emails/notification.txt', context),
                  None, [user.email])
    except Exception:  # an email outage must never break the action that triggered it
        logger.exception('Could not email notification to user %s', user.pk)
