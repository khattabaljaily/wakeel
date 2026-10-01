"""Autopilot: each month, prepare next month's plan without anyone asking.

On the company's `autopilot_day` (in its own timezone) the worker creates next month's plan and
queues its generation. When the designs are rendered, the plan gets a client review link, emailed to
`autopilot_client_email` (or only to the team when it's empty), and the team is notified. The client
approves on the link; with auto-publish on, approved posts then go out on schedule.
"""
import datetime
import logging

from django.conf import settings
from django.core.mail import send_mail
from django.template.loader import render_to_string
from django.utils import timezone, translation
from django.utils.text import format_lazy
from django.utils.translation import gettext_lazy as _

from apps.companies.models import Company, Membership

from .models import ContentPlan, Platform

logger = logging.getLogger(__name__)


def next_month(today):
    return (today.replace(day=1) + datetime.timedelta(days=32)).replace(day=1)


def _defaults(company):
    """Platforms and pace: the autopilot settings, else the latest plan's."""
    last = ContentPlan.objects.filter(company=company).order_by('-month').first()
    platforms = [p for p in company.autopilot_platforms if p in Platform.values] or (last.platforms if last else [])
    return platforms or [Platform.FACEBOOK, Platform.INSTAGRAM], company.autopilot_posts_per_week or (last.posts_per_week if last else 4)


def due_companies(now=None):
    """Companies whose autopilot day has come and that have no plan for next month yet."""
    now = now or timezone.now()
    for company in Company.objects.filter(autopilot=True, is_approved=True, is_active=True):
        if not company.is_usable:
            continue
        today = now.astimezone(company.tzinfo).date()
        if today.day < company.autopilot_day:
            continue
        if ContentPlan.objects.filter(company=company, month=next_month(today)).exists():
            continue
        yield company, next_month(today)


def run_due(now=None):
    """Called by the worker every few minutes. Returns how many plans it started."""
    from apps.jobs.models import Job

    started = 0
    for company, month in due_companies(now):
        owner = company.memberships.filter(role=Membership.Role.OWNER).select_related('user').first()
        platforms, per_week = _defaults(company)
        plan = ContentPlan.objects.create(company=company, month=month, platforms=platforms, posts_per_week=per_week,
                                          created_by=owner.user if owner else None, autopilot=True)
        Job.enqueue(company, Job.Kind.GENERATE_PLAN, plan.created_by, plan_id=plan.pk, autopilot=True)
        logger.info('Autopilot started plan %s for %s', plan.pk, company)
        started += 1
    return started


def deliver(plan):
    """The plan's designs are ready: open a client review link, email it, and tell the team."""
    import secrets

    from apps.notifications.services import managers, notify

    from .review import share_url

    if not plan.share_token:
        plan.share_token = secrets.token_urlsafe(24)
        plan.save(update_fields=['share_token'])
    company, link = plan.company, share_url(plan)
    if company.autopilot_client_email:
        # The client reads the language the brand publishes in.
        try:
            with translation.override('en' if company.content_language == 'en' else 'ar'):
                send_mail(_('خطة المحتوى جاهزة للمراجعة: %(name)s') % {'name': company.name},
                          render_to_string('content/emails/autopilot_client.txt', {'plan': plan, 'company': company, 'link': link}),
                          None, [company.autopilot_client_email])
        except Exception:  # an email outage must not undo the plan
            logger.exception('Could not email the autopilot review link for plan %s', plan.pk)
    title = plan.title or _('الشهر القادم')
    if company.autopilot_client_email:
        message = format_lazy(_('أعدّ الطيار الآلي خطة {title} وأُرسل رابط المراجعة إلى {email}.'),
                              title=title, email=company.autopilot_client_email)
    else:
        message = format_lazy(_('أعدّ الطيار الآلي خطة {title}.'), title=title)
    notify([plan.created_by, *managers(company)], company, message, plan.get_absolute_url(),
           icon='bi-airplane', email=True)
