"""Account approval: self sign-ups wait until a system admin approves them in the console."""
import logging

from django.conf import settings
from django.core.mail import send_mail
from django.template.loader import render_to_string
from django.urls import reverse
from django.utils import timezone

from .models import User

logger = logging.getLogger(__name__)


def signed_up(user):
    admins = list(User.objects.filter(is_superuser=True, is_active=True).exclude(email='').values_list('email', flat=True))
    if admins:
        _send(admins, f'طلب تسجيل جديد في وكيل: {user.display_name}', 'accounts/emails/new_signup.txt', {
            'user': user, 'link': settings.SITE_URL + reverse('ops:signups'),
        })


def approve(user):
    user.is_approved, user.approved_at = True, timezone.now()
    user.save(update_fields=['is_approved', 'approved_at'])
    if user.email:
        _send([user.email], 'تم تفعيل حسابك في وكيل', 'accounts/emails/approved.txt', {
            'user': user, 'link': settings.SITE_URL + reverse('accounts:login'),
        })


def _send(to, subject, template, context):
    try:
        send_mail(subject, render_to_string(template, context), None, to)
    except Exception:  # an email outage must not undo the action
        logger.exception('Could not send "%s"', subject)
