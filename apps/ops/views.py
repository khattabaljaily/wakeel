"""The system admin console (superusers only): a separate area from the subscribers' app, for the
whole platform: subscribers, users, AI usage and cost, jobs and errors, and service status."""
import datetime
import json
from functools import wraps

from django.conf import settings
from django.contrib import messages
from django.contrib.auth.decorators import login_required
from django.core.paginator import Paginator
from django.db import transaction
from django.db.models import Count, Max, Q
from django.http import Http404
from django.shortcuts import get_object_or_404, redirect, render
from django.utils import timezone
from django.views.decorators.http import require_POST

from apps.accounts.models import User
from apps.ai.pricing import DEEPSEEK_PRICES, deepseek_tier
from apps.companies import subscriptions as subscriptions_service
from apps.companies.models import Company, Membership
from apps.content.models import ContentPlan, Post
from apps.jobs.models import Job
from apps.jobs.runner import worker_alive

from . import stats
from .forms import DURATIONS, SubscriptionCreateForm, SubscriptionEditForm


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
            'active_subscriptions': _status_filter(Company.objects.all(), 'active').count(),
            'pending_approval': Company.objects.filter(is_approved=False).count(),
            'expiring': _status_filter(Company.objects.all(), 'active').filter(
                subscription_expires__lte=timezone.localdate() + datetime.timedelta(days=7)).count(),
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


STATUS_FILTERS = [('', 'الكل'), ('active', 'نشط'), ('suspended', 'معلّق'), ('expired', 'منتهي'), ('pending', 'قيد الاعتماد')]


def _status_filter(qs, status):
    today = timezone.localdate()
    live = Q(subscription_expires__isnull=True) | Q(subscription_expires__gte=today)
    return {
        'pending': qs.filter(is_approved=False),
        'suspended': qs.filter(is_approved=True, is_active=False),
        'expired': qs.filter(is_approved=True, is_active=True, subscription_expires__lt=today),
        'active': qs.filter(live, is_approved=True, is_active=True),
    }.get(status, qs)


def _edit_data(company):
    return json.dumps({
        'name': company.name, 'industry': company.industry, 'country': company.country, 'timezone': company.timezone,
        'subscription_plan': company.subscription_plan, 'is_demo': company.is_demo,
        'subscription_expires': company.subscription_expires.isoformat() if company.subscription_expires else '',
    }, ensure_ascii=False)


@superuser_required
def subscriptions(request, create_form=None, edit_form=None, edit_target=None):
    """Subscriptions, as in enjazpms: stats, status tabs, search, and every action from the list."""
    qs = Company.objects.order_by('-created_at')
    status = request.GET.get('status', '')
    q = request.GET.get('q', '').strip()
    if q:
        qs = qs.filter(Q(name__icontains=q) | Q(country__icontains=q) | Q(industry__icontains=q)
                       | Q(memberships__user__email__icontains=q)).distinct()
    qs = _status_filter(qs, status)
    rows = _company_rows(qs, stats.ai_jobs(created_at__gte=stats.year_start()))
    for row in rows:
        row['edit'] = _edit_data(row['company'])
    all_companies = Company.objects.all()
    return render(request, 'ops/subscriptions.html', {
        'page': Paginator(rows, 30).get_page(request.GET.get('page')), 'q': q, 'status': status,
        'filters': STATUS_FILTERS,
        'stats': {key: _status_filter(all_companies, key).count() for key, _ in STATUS_FILTERS},
        'create_form': create_form or SubscriptionCreateForm(initial={'days': '30', 'timezone': 'Asia/Qatar'}),
        'edit_form': edit_form or SubscriptionEditForm(), 'edit_target': edit_target,
        'durations': DURATIONS[1:], 'plans': Company.SUBSCRIPTION_PLANS,
    }, status=400 if (create_form or edit_form) else 200)


def _back(request):
    return redirect(request.POST.get('next') or 'ops:subscriptions')


@superuser_required
@require_POST
def subscription_create(request):
    form = SubscriptionCreateForm(request.POST)
    if not form.is_valid():
        return subscriptions(request, create_form=form)
    with transaction.atomic():
        company = form.save(commit=False)
        company.is_approved, company.approved_at = True, timezone.now()
        days = subscriptions_service.valid_days(form.cleaned_data['days'])
        if days:
            subscriptions_service.extend(company, days)
        company.save()
        user = form.existing_user
        if user is None:
            user = User.objects.create_user(username=form.cleaned_data['owner_email'], email=form.cleaned_data['owner_email'],
                                            password=form.cleaned_data['owner_password'],
                                            first_name=form.cleaned_data['owner_name'])
        Membership.objects.create(company=company, user=user, role=Membership.Role.OWNER)
    messages.success(request, f'تم إنشاء اشتراك «{company.name}» ومالكه {user.email}.')
    return redirect('ops:subscriptions')


@superuser_required
@require_POST
def subscription_update(request, pk):
    company = get_object_or_404(Company, pk=pk)
    form = SubscriptionEditForm(request.POST, instance=company)
    if not form.is_valid():
        return subscriptions(request, edit_form=form, edit_target=company)
    form.save()
    messages.success(request, f'تم حفظ بيانات «{company.name}».')
    return _back(request)


@superuser_required
@require_POST
def subscription_approve(request, pk):
    company = get_object_or_404(Company, pk=pk)
    if company.is_approved:
        messages.info(request, f'«{company.name}» معتمد بالفعل.')
    else:
        subscriptions_service.approve(company, is_demo=request.POST.get('is_demo') == '1',
                                      days=subscriptions_service.valid_days(request.POST.get('days')))
        messages.success(request, f'تم اعتماد «{company.name}»، وأُبلغ مالكه بالبريد.')
    return _back(request)


@superuser_required
@require_POST
def subscription_renew(request, pk):
    company = get_object_or_404(Company, pk=pk)
    days = subscriptions_service.valid_days(request.POST.get('days'))
    if not days:
        messages.error(request, 'اختر مدة صحيحة للتجديد.')
        return _back(request)
    subscriptions_service.extend(company, days)
    if request.POST.get('plan') in dict(Company.SUBSCRIPTION_PLANS):
        company.subscription_plan = request.POST['plan']
    company.save(update_fields=['subscription_expires', 'subscription_plan', 'updated_at'])
    messages.success(request, f'تم تجديد «{company.name}» حتى {company.subscription_expires:%Y-%m-%d}.')
    return _back(request)


@superuser_required
@require_POST
def subscription_toggle(request, pk):
    company = get_object_or_404(Company, pk=pk)
    company.is_active = not company.is_active
    company.save(update_fields=['is_active', 'updated_at'])
    messages.success(request, f'تم تنشيط «{company.name}».' if company.is_active else
                     f'تم تعليق «{company.name}»؛ لن يتمكن فريقها من العمل حتى تعيد تنشيطه.')
    return _back(request)


@superuser_required
@require_POST
def subscription_delete(request, pk):
    company = get_object_or_404(Company, pk=pk)
    if request.POST.get('confirm_name', '').strip() != company.name.strip():
        messages.error(request, 'الاسم المكتوب لا يطابق اسم الشركة، فلم يُحذف شيء.')
        return _back(request)
    name = company.name
    company.delete()  # cascades to plans, posts, media and their files
    messages.success(request, f'تم حذف اشتراك «{name}» وكل بياناته نهائياً.')
    return redirect('ops:subscriptions')


@superuser_required
def company_detail(request, pk):
    company = get_object_or_404(Company, pk=pk)
    total, months = stats.summarize(stats.ai_jobs(company=company, created_at__gte=stats.year_start()))
    return render(request, 'ops/company.html', {
        'target': company, 'total': total, 'months': months, 'edit': _edit_data(company),
        'owner': subscriptions_service.owner(company), 'edit_form': SubscriptionEditForm(),
        'durations': DURATIONS[1:], 'plans': Company.SUBSCRIPTION_PLANS,
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
