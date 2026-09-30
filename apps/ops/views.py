"""The system admin console (superusers only): a separate area from the subscribers' app, for the
whole platform: subscribers, users, AI usage and cost, jobs and errors, and service status."""
import datetime
import json
from functools import wraps

from django.conf import settings
from django.contrib import messages
from django.contrib.auth import login
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
from apps.companies.middleware import SESSION_KEY as COMPANY_SESSION_KEY
from apps.companies.models import Company, Membership
from apps.content.models import ContentPlan, Post
from apps.jobs.models import Job
from apps.jobs.runner import worker_alive

from . import stats, tables
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
    latest = tables.latest_subscriptions()
    status_counts = dict(Post.objects.order_by().values_list('status').annotate(n=Count('pk')))
    total_posts = sum(status_counts.values()) or 1

    return render(request, 'ops/overview.html', {
        'system': _system(), 'this_month': this_month,
        'counts': {
            'companies': Company.objects.count(),
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
        'latest_table': latest, 'latest_rows': latest.rows(sorted(rows, key=lambda r: r['company'].created_at, reverse=True)[:6], request),
        'top': [r for r in sorted(rows, key=lambda r: -r['month']['cost']) if r['month']['jobs']][:6],
        'failures': Job.objects.filter(status=Job.Status.FAILED, created_at__gte=week_ago)
                               .select_related('company', 'created_by').order_by('-created_at')[:5],
    })


STATUS_FILTERS = [('', 'الكل'), ('active', 'نشط'), ('suspended', 'معلّق'), ('expired', 'منتهي'), ('pending', 'قيد الاعتماد')]
IMPERSONATOR_KEY = '_impersonator_id'


def _status_filter(qs, status):
    today = timezone.localdate()
    live = Q(subscription_expires__isnull=True) | Q(subscription_expires__gte=today)
    return {
        'pending': qs.filter(is_approved=False),
        'suspended': qs.filter(is_approved=True, is_active=False),
        'expired': qs.filter(is_approved=True, is_active=True, subscription_expires__lt=today),
        'active': qs.filter(live, is_approved=True, is_active=True),
    }.get(status, qs)


def _subscription_data(company, owner=None, members=None, posts=None):
    """Everything the view / edit dialogs show for one subscription, as JSON for the row's buttons."""
    return json.dumps({
        'id': company.pk, 'name': company.name, 'initials': company.initials, 'color': company.primary_color,
        'industry': company.industry, 'email': company.email, 'phone': company.phone, 'city': company.city,
        'country': company.country, 'timezone': company.timezone, 'is_demo': company.is_demo,
        'is_active': company.is_active, 'is_approved': company.is_approved,
        'subscription_start': company.subscription_start.isoformat() if company.subscription_start else '',
        'subscription_expires': company.subscription_expires.isoformat() if company.subscription_expires else '',
        'days': company.days_until_expiry, 'status': company.subscription_status,
        'status_label': company.subscription_status_label,
        'created': timezone.localtime(company.created_at).strftime('%Y-%m-%d'),
        'owner_name': owner.display_name if owner else '', 'owner_email': owner.email if owner else '',
        'members': members, 'posts': posts,
    }, ensure_ascii=False)


@superuser_required
def subscriptions(request, create_form=None, edit_form=None, edit_target=None):
    """Subscriptions, as in enjazpms: status tabs with counts, search, and every action on each row.
    Rows come from subscriptions_data a page at a time (a DataTable; cards on phones)."""
    status = request.GET.get('status', '')
    all_companies = Company.objects.all()
    return render(request, 'ops/subscriptions.html', {
        'table': tables.subscriptions(), 'status': status if status in dict(STATUS_FILTERS) else '',
        'filters': STATUS_FILTERS,
        'stats': {key: _status_filter(all_companies, key).count() for key, _ in STATUS_FILTERS},
        'create_form': create_form or SubscriptionCreateForm(initial={
            'timezone': 'Asia/Qatar', 'subscription_start': timezone.localdate(),
            'subscription_expires': timezone.localdate() + datetime.timedelta(days=30)}),
        'edit_form': edit_form or SubscriptionEditForm(), 'edit_target': edit_target,
        'durations': DURATIONS[1:],
    }, status=400 if (create_form or edit_form) else 200)


@superuser_required
def subscriptions_data(request):
    queryset = _status_filter(Company.objects.annotate(members=Count('memberships', distinct=True),
                                                       post_count=Count('posts', distinct=True)),
                              request.GET.get('status', '')).order_by('-created_at')

    def prepare(companies):
        owners = {m.company_id: m.user for m in Membership.objects.filter(
            company__in=companies, role=Membership.Role.OWNER).select_related('user')}
        for c in companies:
            c.owner = owners.get(c.pk)
            c.data = _subscription_data(c, c.owner, c.members, c.post_count)

    return tables.subscriptions().json(request, queryset, prepare=prepare)


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
    if request.POST.get('is_demo') in ('0', '1'):  # renewing is also when a trial becomes paid
        company.is_demo = request.POST['is_demo'] == '1'
    company.save(update_fields=['subscription_expires', 'is_demo', 'updated_at'])
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
@require_POST
def subscription_login_as(request, pk):
    """Enter the subscriber's workspace as its owner (as in enjazpms); the admin's password is asked again."""
    company = get_object_or_404(Company, pk=pk)
    if not request.user.check_password(request.POST.get('password', '')):
        messages.error(request, 'كلمة مرور المشرف غير صحيحة.')
        return _back(request)
    owner = subscriptions_service.owner(company)
    if owner is None or not owner.is_active:
        messages.error(request, f'لا يوجد مالك نشط لـ «{company.name}».')
        return _back(request)
    admin_id = request.user.pk
    login(request, owner, backend='apps.accounts.backends.EmailOrUsernameBackend')  # starts a fresh session
    request.session[IMPERSONATOR_KEY] = admin_id
    request.session[COMPANY_SESSION_KEY] = company.pk
    return redirect('core:dashboard')


@superuser_required
def company_detail(request, pk):
    company = get_object_or_404(Company, pk=pk)
    total, months = stats.summarize(stats.ai_jobs(company=company, created_at__gte=stats.year_start()))
    owner = subscriptions_service.owner(company)
    months_table = tables.usage_months()
    return render(request, 'ops/company.html', {
        'target': company, 'total': total, 'owner': owner,
        'months_table': months_table, 'months_rows': months_table.rows(months, request),
        'jobs_table': tables.jobs(company),
        'data': _subscription_data(company, owner, company.memberships.count(), company.posts.count()),
        'edit_form': SubscriptionEditForm(), 'durations': DURATIONS[1:],
        'members': company.memberships.select_related('user').order_by('created_at'),
        'plans': company.plans.annotate(n=Count('posts'))[:12],
        'posts_by_status': {Post.Status(s).label: n for s, n in
                            company.posts.order_by().values_list('status').annotate(n=Count('pk'))},
        'accounts': company.social_accounts.all(),
    })


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
    by_model, by_kind = tables.breakdown('modelsTable', 'النموذج'), tables.breakdown('kindsTable', 'المهمة')
    months_table, companies_table = tables.usage_months(), tables.usage_companies()
    return render(request, 'ops/usage.html', {
        'system': _system(), 'total': total,
        'months_table': months_table, 'months_rows': months_table.rows(months, request),
        'models_table': by_model, 'models_rows': by_model.rows(models.values(), request),
        'kinds_table': by_kind, 'kinds_rows': by_kind.rows(kinds.values(), request),
        'companies_table': companies_table, 'companies_rows': companies_table.rows(rows, request),
        'cost_series': stats.monthly_series(year_jobs, lambda j: j.created_at, lambda j: float(j.cost_usd or 0)),
    })


@superuser_required
def jobs(request):
    return render(request, 'ops/jobs.html', {
        'table': tables.jobs(), 'statuses': Job.Status.choices, 'kinds': Job.Kind.choices,
        'status': request.GET.get('status', ''), 'kind': request.GET.get('kind', ''),
    })


@superuser_required
def jobs_data(request):
    """Jobs for the DataTables (all, or ?company=ID), filtered by status / kind."""
    queryset = Job.objects.select_related('company', 'created_by').order_by('-created_at')
    company = request.GET.get('company', '')
    if company.isdigit():
        queryset = queryset.filter(company_id=company)
    if request.GET.get('status') in Job.Status.values:
        queryset = queryset.filter(status=request.GET['status'])
    if request.GET.get('kind') in Job.Kind.values:
        queryset = queryset.filter(kind=request.GET['kind'])
    table = tables.jobs(Company(pk=int(company)) if company.isdigit() else None)
    return table.json(request, queryset, context={'show_company': not company.isdigit()})


@superuser_required
def system(request):
    return render(request, 'ops/system.html', {
        'system': _system(),
        'queue': {s: n for s, n in Job.objects.filter(status__in=[Job.Status.PENDING, Job.Status.RUNNING])
                  .order_by().values_list('status').annotate(n=Count('pk'))},
        'oldest_pending': Job.objects.filter(status=Job.Status.PENDING).order_by('created_at').first(),
    })
