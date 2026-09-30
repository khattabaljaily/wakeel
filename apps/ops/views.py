"""The system admin console (superusers only): a separate area from the subscribers' app, for the
whole platform: subscribers, users, AI usage and cost, jobs and errors, and service status."""
import datetime
from functools import wraps

from django.conf import settings
from django.contrib import messages
from django.contrib.auth.decorators import login_required
from django.core.paginator import Paginator
from django.db.models import Count, Max, Q
from django.http import Http404
from django.shortcuts import get_object_or_404, redirect, render
from django.utils import timezone
from django.views.decorators.http import require_POST

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
            raise Http404  # the console's existence isn't advertised
        return view(request, *args, **kwargs)
    return wrapped


def _system():
    deepseek = settings.AI_PROVIDER == 'deepseek'
    model = settings.DEEPSEEK_MODEL if deepseek else settings.ANTHROPIC_MODEL
    return {
        'provider': 'DeepSeek' if deepseek else 'Claude (Anthropic)', 'model': model,
        'ai_enabled': settings.AI_ENABLED, 'ai_key_name': settings.AI_KEY_NAME,
        'worker_alive': worker_alive(), 'email': bool(settings.EMAIL_HOST), 'meta': settings.META_ENABLED,
        'site_url': settings.SITE_URL, 'debug': settings.DEBUG,
        'prices': DEEPSEEK_PRICES.get(deepseek_tier(model)) if deepseek else None,
        'off_peak': settings.DEEPSEEK_OFF_PEAK_UTC,
        'flat_prices': (settings.AI_PRICE_INPUT_PER_MTOK, settings.AI_PRICE_OUTPUT_PER_MTOK),
    }


def _company_rows(companies, year_jobs):
    """Each company with its owner, counts, and AI usage this month and over the year."""
    by_company = {}
    month_start = stats.month_start()
    for job in year_jobs:
        row = by_company.setdefault(job.company_id, {'month': stats.blank(), 'year': stats.blank()})
        stats.add(row['year'], job)
        if job.created_at >= month_start:
            stats.add(row['month'], job)
    owners = {m.company_id: m.user for m in Membership.objects.filter(role=Membership.Role.OWNER).select_related('user')}
    companies = companies.annotate(
        members=Count('memberships', distinct=True), plan_count=Count('plans', distinct=True),
        post_count=Count('posts', distinct=True),
        published=Count('posts', filter=Q(posts__status=Post.Status.PUBLISHED), distinct=True),
        last_post=Max('posts__updated_at'),
    )
    empty = {'month': stats.blank(), 'year': stats.blank()}
    return [{'company': c, 'owner': owners.get(c.pk), **by_company.get(c.pk, empty)} for c in companies]


@superuser_required
def overview(request):
    now = timezone.now()
    month_start = stats.month_start()
    year_jobs = list(stats.ai_jobs(created_at__gte=stats.year_start()))
    this_month = stats.summarize(j for j in year_jobs if j.created_at >= month_start)[0]
    week_ago = now - datetime.timedelta(days=7)

    active = set(Job.objects.filter(created_at__gte=month_start).values_list('company_id', flat=True))
    active |= set(Post.objects.filter(updated_at__gte=month_start).values_list('company_id', flat=True))
    rows = _company_rows(Company.objects.all(), year_jobs)
    status_counts = dict(Post.objects.order_by().values_list('status').annotate(n=Count('pk')))
    total_posts = sum(status_counts.values()) or 1

    return render(request, 'ops/overview.html', {
        'system': _system(), 'this_month': this_month,
        'counts': {
            'companies': Company.objects.count(), 'users': User.objects.filter(is_superuser=False).count(),
            'active_companies': len(active),
            'new_companies': Company.objects.filter(created_at__gte=month_start).count(),
            'posts_month': Post.objects.filter(created_at__gte=month_start).count(),
            'published_month': Post.objects.filter(published_at__gte=month_start).count(),
            'plans_month': ContentPlan.objects.filter(created_at__gte=month_start).count(),
            'failed_week': Job.objects.filter(status=Job.Status.FAILED, created_at__gte=week_ago).count(),
            'pending': Job.objects.filter(status__in=[Job.Status.PENDING, Job.Status.RUNNING]).count(),
        },
        'cost_series': stats.monthly_series(year_jobs, lambda j: j.created_at, lambda j: float(j.cost_usd or 0)),
        'signup_series': stats.monthly_series(Company.objects.filter(created_at__gte=stats.year_start()),
                                              lambda c: c.created_at),
        'post_status': [{'key': s, 'label': label, 'n': status_counts.get(s, 0),
                         'pct': round(status_counts.get(s, 0) * 100 / total_posts)} for s, label in Post.Status.choices],
        'latest': sorted(rows, key=lambda r: r['company'].created_at, reverse=True)[:6],
        'top': [r for r in sorted(rows, key=lambda r: -r['month']['cost']) if r['month']['jobs']][:6],
        'failures': Job.objects.filter(status=Job.Status.FAILED, created_at__gte=week_ago)
                               .select_related('company', 'created_by').order_by('-created_at')[:5],
    })


@superuser_required
def companies(request):
    qs = Company.objects.order_by('-created_at')
    q = request.GET.get('q', '').strip()
    if q:
        qs = qs.filter(Q(name__icontains=q) | Q(country__icontains=q) | Q(industry__icontains=q)
                       | Q(memberships__user__email__icontains=q)).distinct()
    rows = _company_rows(qs, stats.ai_jobs(created_at__gte=stats.year_start()))
    sort = request.GET.get('sort', 'new')
    if sort == 'cost':
        rows.sort(key=lambda r: -r['year']['cost'])
    elif sort == 'posts':
        rows.sort(key=lambda r: -r['company'].post_count)
    return render(request, 'ops/companies.html', {
        'page': Paginator(rows, 30).get_page(request.GET.get('page')), 'q': q, 'sort': sort,
        'total': Company.objects.count(),
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
def users(request):
    qs = User.objects.order_by('-date_joined').prefetch_related('memberships__company')
    q = request.GET.get('q', '').strip()
    state = request.GET.get('state', '')
    if q:
        qs = qs.filter(Q(email__icontains=q) | Q(first_name__icontains=q) | Q(last_name__icontains=q))
    if state == 'inactive':
        qs = qs.filter(is_active=False)
    elif state == 'never':
        qs = qs.filter(last_login__isnull=True)
    elif state == 'admins':
        qs = qs.filter(is_superuser=True)
    subscribers = User.objects.filter(is_superuser=False)
    return render(request, 'ops/users.html', {
        'page': Paginator(qs, 40).get_page(request.GET.get('page')), 'q': q, 'state': state,
        'counts': {
            'all': subscribers.count(), 'active': subscribers.filter(is_active=True).count(),
            'inactive': subscribers.filter(is_active=False).count(),
            'never': subscribers.filter(last_login__isnull=True).count(),
            'admins': User.objects.filter(is_superuser=True).count(),
        },
    })


@superuser_required
@require_POST
def user_toggle_active(request, pk):
    user = get_object_or_404(User, pk=pk, is_superuser=False)  # system admins aren't suspended from here
    user.is_active = not user.is_active
    user.save(update_fields=['is_active'])
    messages.success(request, f'تم تفعيل حساب {user.email}.' if user.is_active else
                     f'تم إيقاف حساب {user.email}؛ لن يتمكن من تسجيل الدخول.')
    return redirect(request.POST.get('next') or 'ops:users')


@superuser_required
def usage(request):
    year_jobs = list(stats.ai_jobs(created_at__gte=stats.year_start()))
    total, months = stats.summarize(year_jobs)
    models = {}
    for job in year_jobs:
        stats.add(models.setdefault(job.model or '—', stats.blank(job.model or '—')), job)
    kinds = {}
    for job in year_jobs:
        stats.add(kinds.setdefault(job.get_kind_display(), stats.blank(job.get_kind_display())), job)
    rows = [r for r in _company_rows(Company.objects.all(), year_jobs) if r['year']['jobs']]
    return render(request, 'ops/usage.html', {
        'system': _system(), 'total': total, 'months': months,
        'by_model': sorted(models.values(), key=lambda r: -r['cost']),
        'by_kind': sorted(kinds.values(), key=lambda r: -r['cost']),
        'by_company': sorted(rows, key=lambda r: -r['year']['cost']),
        'cost_series': stats.monthly_series(year_jobs, lambda j: j.created_at, lambda j: float(j.cost_usd or 0)),
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


@superuser_required
def system(request):
    return render(request, 'ops/system.html', {
        'system': _system(),
        'queue': {s: n for s, n in Job.objects.filter(status__in=[Job.Status.PENDING, Job.Status.RUNNING])
                  .order_by().values_list('status').annotate(n=Count('pk'))},
        'oldest_pending': Job.objects.filter(status=Job.Status.PENDING).order_by('created_at').first(),
    })
