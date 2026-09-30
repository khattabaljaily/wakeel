"""The system admin panel (superusers only): every company's activity, AI usage, cost and failures."""
import datetime
from functools import wraps

from django.conf import settings
from django.contrib.auth.decorators import login_required
from django.core.paginator import Paginator
from django.db.models import Count, Q
from django.http import Http404
from django.shortcuts import get_object_or_404, render
from django.utils import timezone

from apps.accounts.models import User
from apps.ai.pricing import DEEPSEEK_PRICES, deepseek_tier
from apps.companies.models import Company, Membership
from apps.content.models import ContentPlan, Post
from apps.jobs.models import Job
from apps.jobs.runner import worker_alive

from . import stats


def superuser_required(view):
    @login_required
    @wraps(view)
    def wrapped(request, *args, **kwargs):
        if not request.user.is_superuser:
            raise Http404  # the panel's existence isn't advertised
        return view(request, *args, **kwargs)
    return wrapped


def _system():
    deepseek = settings.AI_PROVIDER == 'deepseek'
    model = settings.DEEPSEEK_MODEL if deepseek else settings.ANTHROPIC_MODEL
    return {
        'provider': 'DeepSeek' if deepseek else 'Claude (Anthropic)', 'model': model,
        'ai_enabled': settings.AI_ENABLED, 'ai_key_name': settings.AI_KEY_NAME,
        'worker_alive': worker_alive(), 'email': bool(settings.EMAIL_HOST), 'meta': settings.META_ENABLED,
        'site_url': settings.SITE_URL,
        'prices': DEEPSEEK_PRICES.get(deepseek_tier(model)) if deepseek else None,
        'off_peak': settings.DEEPSEEK_OFF_PEAK_UTC,
        'flat_prices': (settings.AI_PRICE_INPUT_PER_MTOK, settings.AI_PRICE_OUTPUT_PER_MTOK),
    }


@superuser_required
def overview(request):
    year_jobs = list(stats.ai_jobs(created_at__gte=stats.year_start()))
    total, months = stats.summarize(year_jobs)
    this_month = stats.summarize(j for j in year_jobs if j.created_at >= stats.month_start())[0]

    by_company = {}
    for job in year_jobs:
        row = by_company.setdefault(job.company_id, {'month': stats.blank(), 'year': stats.blank()})
        stats.add(row['year'], job)
        if job.created_at >= stats.month_start():
            stats.add(row['month'], job)
    companies = (Company.objects.annotate(
        members=Count('memberships', distinct=True), plan_count=Count('plans', distinct=True),
        post_count=Count('posts', distinct=True),
        published=Count('posts', filter=Q(posts__status=Post.Status.PUBLISHED), distinct=True),
    ).order_by('-created_at'))
    owners = {m.company_id: m.user for m in Membership.objects.filter(role=Membership.Role.OWNER).select_related('user')}
    company_rows = sorted(
        [{'company': c, 'owner': owners.get(c.pk), **by_company.get(c.pk, {'month': stats.blank(), 'year': stats.blank()})}
         for c in companies],
        key=lambda r: (-r['year']['cost'], -r['year']['input']))

    week_ago = timezone.now() - datetime.timedelta(days=7)
    return render(request, 'ops/overview.html', {
        'system': _system(), 'total': total, 'months': months, 'this_month': this_month,
        'company_rows': company_rows,
        'counts': {
            'companies': Company.objects.count(), 'users': User.objects.count(),
            'plans': ContentPlan.objects.count(), 'posts': Post.objects.count(),
        },
        'failures': Job.objects.filter(status=Job.Status.FAILED, created_at__gte=week_ago)
                               .select_related('company').order_by('-created_at')[:8],
        'failed_week': Job.objects.filter(status=Job.Status.FAILED, created_at__gte=week_ago).count(),
        'pending': Job.objects.filter(status__in=[Job.Status.PENDING, Job.Status.RUNNING]).count(),
    })


@superuser_required
def company_detail(request, pk):
    company = get_object_or_404(Company, pk=pk)
    total, months = stats.summarize(stats.ai_jobs(company=company, created_at__gte=stats.year_start()))
    return render(request, 'ops/company.html', {
        'target': company, 'total': total, 'months': months,
        'members': company.memberships.select_related('user').order_by('created_at'),
        'plans': company.plans.annotate(n=Count('posts'))[:12],
        'posts_by_status': {Post.Status(s).label: n for s, n in
                            company.posts.order_by().values_list('status').annotate(n=Count('pk'))},
        'accounts': company.social_accounts.all(),
        'jobs': Job.objects.filter(company=company).select_related('created_by').order_by('-created_at')[:30],
    })


@superuser_required
def jobs(request):
    qs = Job.objects.select_related('company', 'created_by').order_by('-created_at')
    status = request.GET.get('status', '')
    kind = request.GET.get('kind', '')
    if status in Job.Status.values:
        qs = qs.filter(status=status)
    if kind in Job.Kind.values:
        qs = qs.filter(kind=kind)
    return render(request, 'ops/jobs.html', {
        'page': Paginator(qs, 50).get_page(request.GET.get('page')),
        'status': status, 'kind': kind, 'statuses': Job.Status.choices, 'kinds': Job.Kind.choices,
    })
