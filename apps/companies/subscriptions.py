"""Subscription lifecycle, as in enjazpms: sign-up -> awaiting approval -> approved (trial or paid, with a
duration) -> renewed / suspended / reactivated / deleted. The console (apps.ops) drives it."""
import datetime
import logging

from django.conf import settings
from django.core.mail import send_mail
from django.template.loader import render_to_string
from django.urls import reverse
from django.utils import timezone

from apps.accounts.models import User

from .models import Company, Membership

logger = logging.getLogger(__name__)

MAX_DAYS = 3650


def owner(company):
    membership = company.memberships.filter(role=Membership.Role.OWNER).select_related('user').first()
    return membership.user if membership else None


def extend(company, days):
    """Push the end date by `days`, from today or from the current end if it's still ahead."""
    today = timezone.localdate()
    base = company.subscription_expires if company.subscription_expires and company.subscription_expires >= today else today
    company.subscription_expires = base + datetime.timedelta(days=days)


def valid_days(value):
    try:
        days = int(value)
    except (TypeError, ValueError):
        return None
    return days if 0 < days <= MAX_DAYS else None


def signed_up(company, user):
    """A subscriber created a company themselves: it waits for an admin, who is told by email."""
    company.is_approved, company.is_demo = False, True
    company.save(update_fields=['is_approved', 'is_demo'])
    admins = list(User.objects.filter(is_superuser=True, is_active=True).exclude(email='').values_list('email', flat=True))
    if admins:
        _send(admins, f'طلب اشتراك جديد: {company.name}', 'companies/emails/new_signup.txt', {
            'company': company, 'user': user,
            'link': settings.SITE_URL + reverse('ops:subscriptions') + '?status=pending',
        })


def approve(company, *, is_demo, days=None):
    company.is_approved, company.approved_at, company.is_demo = True, timezone.now(), is_demo
    if days:
        extend(company, days)
    company.save(update_fields=['is_approved', 'approved_at', 'is_demo', 'subscription_expires', 'updated_at'])
    user = owner(company)
    if user and user.email:
        _send([user.email], f'تم تفعيل حسابك في وكيل: {company.name}', 'companies/emails/approved.txt', {
            'company': company, 'user': user, 'link': settings.SITE_URL + reverse('accounts:login'),
        })


def _send(to, subject, template, context):
    try:
        send_mail(subject, render_to_string(template, context), None, to)
    except Exception:  # an email outage must not undo the admin's action
        logger.exception('Could not send "%s"', subject)
