"""Background work for insights: refresh numbers, write monthly reports, and the worker's schedule."""
import datetime
import logging
import secrets

from django.conf import settings
from django.core.mail import send_mail
from django.template.loader import render_to_string
from django.urls import reverse
from django.utils import timezone, translation
from django.utils.translation import gettext_lazy as _

from apps.companies.models import Company
from apps.social.models import SocialAccount

from . import services
from .models import MonthlyReport, PostInsight

logger = logging.getLogger(__name__)

ARABIC_MONTHS = ['يناير', 'فبراير', 'مارس', 'أبريل', 'مايو', 'يونيو', 'يوليو', 'أغسطس', 'سبتمبر', 'أكتوبر', 'نوفمبر', 'ديسمبر']
REPORT_FROM_DAY = 1  # a month's report is written from its first days after it ends
# Automatic reports (emailed to clients) start with the first full month after insights went live;
# earlier months would have partial numbers. Reports for any month can still be made by hand.
AUTO_REPORTS_FROM = datetime.date(2026, 10, 1)


def previous_month(today):
    return (today.replace(day=1) - datetime.timedelta(days=1)).replace(day=1)


def month_label(month):
    return f'{ARABIC_MONTHS[month.month - 1]} {month.year}'


def share_url(report):
    return settings.SITE_URL + reverse('insights_public:public_report', args=[report.share_token]) if report.share_token else ''


# --- Jobs -------------------------------------------------------------------

def run_fetch_insights(job):
    updated, problems = services.collect(job.company)
    if problems and not updated:
        job.error_detail = '\n'.join(problems)
        return _('تعذّر قراءة الأرقام: %(problem)s') % {'problem': problems[0]}
    return _('تم تحديث أرقام %(count)s منشور.') % {'count': updated}


def run_generate_report(job):
    from apps.ai import report as ai_report
    from apps.core import language

    rep = MonthlyReport.objects.select_related('company').get(pk=job.params['report_id'], company=job.company)
    company = rep.company
    job.set_progress(20, _('جارٍ قراءة أرقام الشهر…'))
    start, end = services.month_bounds(rep.month, company)
    stats = services.summarize(company, start, end)
    rep.stats = stats
    try:
        result = ai_report.write_report(company, month_label(rep.month), stats,
                                        language.name(language.of_user(job.created_by) if job.created_by_id else language.of_team(company)))
    except Exception as exc:
        rep.status, rep.error = MonthlyReport.Status.FAILED, str(exc)
        rep.save(update_fields=['status', 'error', 'stats'])
        raise
    job.add_usage(result)
    data = result.data
    rep.summary = str(data.get('summary') or '').strip()
    rep.wins = [str(w) for w in data.get('wins') or [] if w][:3]
    rep.recommendations = [str(r) for r in data.get('recommendations') or [] if r][:3]
    rep.status, rep.error = MonthlyReport.Status.READY, ''
    if not rep.share_token:
        rep.share_token = secrets.token_urlsafe(24)
    rep.save()
    if job.params.get('deliver'):
        deliver(rep)
    return _('تم إعداد تقرير %(month)s.') % {'month': month_label(rep.month)}


def deliver(rep):
    """Tell the team the report is ready, and email the client when one is set (the autopilot's client email)."""
    from apps.notifications.services import managers, notify

    company, link = rep.company, share_url(rep)
    if company.autopilot_client_email and not rep.emailed_at:
        try:
            with translation.override('en' if company.content_language == 'en' else 'ar'):
                send_mail(_('تقرير أداء %(month)s: %(name)s') % {'month': month_label(rep.month), 'name': company.name},
                          render_to_string('insights/emails/report_client.txt',
                                           {'company': company, 'month': month_label(rep.month), 'link': link, 'summary': rep.summary}),
                          None, [company.autopilot_client_email])
            rep.emailed_at = timezone.now()
            rep.save(update_fields=['emailed_at'])
        except Exception:
            logger.exception('Could not email report %s', rep.pk)
    notify(managers(company), company, _('تقرير أداء %(month)s جاهز.') % {'month': month_label(rep.month)},
           reverse('insights:report', args=[rep.pk]), icon='bi-graph-up-arrow', email=True)


# --- Worker schedule --------------------------------------------------------

def _usable_companies():
    return [c for c in Company.objects.filter(is_approved=True, is_active=True, social_accounts__isnull=False).distinct()
            if c.is_usable]


def run_due(now=None):
    """Called by the worker every few minutes: queue insight refreshes and last month's report. Returns jobs queued."""
    from apps.jobs.models import Job

    now = now or timezone.now()
    queued = 0
    for company in _usable_companies():
        active = Job.objects.filter(company=company, status__in=[Job.Status.PENDING, Job.Status.RUNNING])
        last = PostInsight.objects.filter(post__company=company).order_by('-fetched_at').values_list('fetched_at', flat=True).first()
        has_posts = company.posts.filter(status='published').exists()
        stale = last is None or now - last >= services.REFRESH_AFTER
        recently_tried = Job.objects.filter(company=company, kind=Job.Kind.FETCH_INSIGHTS,
                                            created_at__gte=now - services.REFRESH_AFTER).exists()
        if has_posts and stale and not recently_tried and not active.filter(kind=Job.Kind.FETCH_INSIGHTS).exists():
            Job.enqueue(company, Job.Kind.FETCH_INSIGHTS)
            queued += 1
        today = now.astimezone(company.tzinfo).date()
        month = previous_month(today)
        if (today.day >= REPORT_FROM_DAY and month >= AUTO_REPORTS_FROM
                and not MonthlyReport.objects.filter(company=company, month=month).exists()):
            start, end = services.month_bounds(month, company)
            if PostInsight.objects.filter(post__company=company, post__published_at__gte=start, post__published_at__lt=end).exists():
                rep = MonthlyReport.objects.create(company=company, month=month, share_token=secrets.token_urlsafe(24))
                Job.enqueue(company, Job.Kind.GENERATE_REPORT, None, report_id=rep.pk, deliver=True)
                queued += 1
    return queued
