"""The system admin console (superusers only): a separate area from the subscribers' app, for the
whole platform: subscribers, users, AI usage and cost, jobs and errors, and service status."""
import datetime
import json
from decimal import Decimal
from functools import wraps

from django.conf import settings
from django.contrib import messages
from django.core.serializers.json import DjangoJSONEncoder
from django.contrib.auth import login
from django.contrib.auth.decorators import login_required
from django.core.cache import cache
from django.core.paginator import Paginator
from django.db import transaction
from django.db.models import Count, Max, Q
from django.http import Http404
from django.shortcuts import get_object_or_404, redirect, render
from django.utils import timezone
from django.utils.translation import gettext_lazy as _
from django.views.decorators.http import require_POST

from apps.accounts import approval
from apps.accounts.models import User
from apps.ai.pricing import DEEPSEEK_PRICES, deepseek_tier
from apps.companies import subscriptions as subscriptions_service
from apps.companies.middleware import SESSION_KEY as COMPANY_SESSION_KEY
from apps.companies.models import Company, Membership
from apps.content.models import ContentPlan, Post
from apps.credits import catalog, charging
from apps.credits.models import WalletTransaction
from apps.jobs.models import Job
from apps.jobs.runner import worker_alive

from enjaz_operators import registry, web as operator_names

from apps.companies import operators as operators_service

from . import purge, stats, tables
from .forms import SubscriptionCreateForm, SubscriptionEditForm


def superuser_required(view):
    @login_required
    @wraps(view)
    def wrapped(request, *args, **kwargs):
        if not request.user.is_superuser:
            raise Http404  # the console's existence isn't advertised
        return view(request, *args, **kwargs)
    return wrapped


def _system():
    from apps.ai.client import resolve

    def route(tier):
        try:
            provider, model = resolve(tier)
        except Exception:
            return None
        return {'provider': 'DeepSeek' if provider == 'deepseek' else 'Claude (Anthropic)', 'model': model}

    routes = {tier: route(tier) for tier in ('interactive', 'background', 'premium')}
    first = next((r for r in routes.values() if r), {'provider': '—', 'model': ''})
    return {
        'provider': first['provider'], 'model': first['model'], 'routes': routes,
        'ai_enabled': settings.AI_ENABLED, 'ai_key_name': settings.AI_KEY_NAME,
        'worker_alive': worker_alive(), 'email': bool(settings.EMAIL_HOST), 'meta': settings.META_ENABLED,
        'site_url': settings.SITE_URL, 'debug': settings.DEBUG,
        'prices': DEEPSEEK_PRICES.get(deepseek_tier(settings.DEEPSEEK_MODEL)) if settings.DEEPSEEK_API_KEY else None,
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


def _product_totals(month_start):
    """What the other sections of the product are doing, platform-wide: documents, money, people."""
    from django.db.models import Sum
    from apps.documents.models import Document
    from apps.library.models import Record
    from apps.credits.models import Wallet
    charged, refunded, net = charging.revenue(since=month_start)
    topups = WalletTransaction.objects.filter(created_at__gte=month_start, action=WalletTransaction.TOPUP).aggregate(s=Sum('delta'))['s'] or 0
    held = Wallet.objects.filter(is_exempt=False).aggregate(s=Sum('balance'))['s'] or 0
    empty = Wallet.objects.filter(is_exempt=False, balance__lte=0, company__is_active=True).count()
    return {
        'net': catalog.money(net), 'topups': catalog.money(topups), 'held': catalog.money(held), 'empty_wallets': empty,
        'documents_month': Document.all_companies.filter(created_at__gte=month_start).count(),
        'records': Record.all_companies.count(),
        'users': User.objects.count(), 'new_users': User.objects.filter(date_joined__gte=month_start).count(),
    }


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
            'active_companies': len(active),
            'new_companies': Company.objects.filter(created_at__gte=month_start).count(),
            'posts_month': Post.objects.filter(created_at__gte=month_start).count(),
            'published_month': Post.objects.filter(published_at__gte=month_start).count(),
            'plans_month': ContentPlan.objects.filter(created_at__gte=month_start).count(),
            'failed_week': Job.objects.filter(status=Job.Status.FAILED, created_at__gte=week_ago).count(),
            'pending': Job.objects.filter(status__in=[Job.Status.PENDING, Job.Status.RUNNING]).count(),
        },
        'revenue': charging.revenue_usd(since=stats.year_start()),
        'product': _product_totals(month_start), 'budget': _budget(),
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


STATUS_FILTERS = [('', _('الكل')), ('active', _('نشط')), ('suspended', _('معلّق')), ('pending', _('قيد الاعتماد'))]
IMPERSONATOR_KEY = '_impersonator_id'


def _status_filter(qs, status):
    return {
        'pending': qs.filter(is_approved=False),
        'suspended': qs.filter(is_approved=True, is_active=False),
        'active': qs.filter(is_approved=True, is_active=True),
    }.get(status, qs)


def _subscription_data(company, owner=None, members=None, posts=None, balance=''):
    """Everything the view / edit dialogs show for one subscription, as JSON for the row's buttons."""
    return json.dumps(cls=DjangoJSONEncoder, obj={
        'id': company.pk, 'name': company.name, 'initials': company.initials, 'color': company.primary_color,
        'industry': company.industry, 'email': company.email, 'phone': company.phone, 'city': company.city,
        'country': company.country, 'timezone': company.timezone,
        'is_active': company.is_active, 'is_approved': company.is_approved,
        'balance': balance, 'status': company.subscription_status,
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
        'create_form': create_form or SubscriptionCreateForm(initial={'timezone': 'Asia/Qatar'}),
        'edit_form': edit_form or SubscriptionEditForm(), 'edit_target': edit_target,
    }, status=400 if (create_form or edit_form) else 200)


@superuser_required
def subscriptions_data(request):
    queryset = _status_filter(Company.objects.select_related('wallet').annotate(members=Count('memberships', distinct=True),
                                                       post_count=Count('posts', distinct=True)),
                              request.GET.get('status', '')).order_by('-created_at')

    def prepare(companies):
        owners = {m.company_id: m.user for m in Membership.objects.filter(
            company__in=companies, role=Membership.Role.OWNER).select_related('user')}
        for c in companies:
            c.owner = owners.get(c.pk)
            wallet = getattr(c, 'wallet', None)
            c.balance_amount = catalog.money(wallet.balance if wallet else 0)
            c.data = _subscription_data(c, c.owner, c.members, c.post_count, c.balance_amount)

    return tables.subscriptions().json(request, queryset, prepare=prepare)


def _back_to(request, pk):
    """Back to the page the form came from (same site only), else the company's page."""
    from django.utils.http import url_has_allowed_host_and_scheme
    target = request.POST.get('next') or ''
    if target and url_has_allowed_host_and_scheme(target, allowed_hosts={request.get_host()}):
        return redirect(target)
    return redirect('ops:company', pk=pk)


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
    messages.success(request, _('تم إنشاء اشتراك «%(name)s» ومالكه %(email)s.') % {'name': company.name, 'email': user.email})
    return redirect('ops:subscriptions')


@superuser_required
@require_POST
def subscription_update(request, pk):
    company = get_object_or_404(Company, pk=pk)
    form = SubscriptionEditForm(request.POST, instance=company)
    if not form.is_valid():
        return subscriptions(request, edit_form=form, edit_target=company)
    form.save()
    messages.success(request, _('تم حفظ بيانات «%(name)s».') % {'name': company.name})
    return _back(request)


@superuser_required
@require_POST
def subscription_approve(request, pk):
    company = get_object_or_404(Company, pk=pk)
    if company.is_approved:
        messages.info(request, _('«%(name)s» معتمد بالفعل.') % {'name': company.name})
    else:
        subscriptions_service.approve(company)
        messages.success(request, _('تم اعتماد «%(name)s»، وأُبلغ مالكه بالبريد.') % {'name': company.name})
    return _back(request)


@superuser_required
@require_POST
def subscription_toggle(request, pk):
    company = get_object_or_404(Company, pk=pk)
    company.is_active = not company.is_active
    company.save(update_fields=['is_active', 'updated_at'])
    messages.success(request, _('تم تنشيط «%(name)s».') % {'name': company.name} if company.is_active else
                     _('تم تعليق «%(name)s»؛ لن يتمكن فريقها من العمل حتى تعيد تنشيطه.') % {'name': company.name})
    return _back(request)


@superuser_required
@require_POST
def subscription_delete(request, pk):
    company = get_object_or_404(Company, pk=pk)
    if request.POST.get('confirm_name', '').strip() != company.name.strip():
        messages.error(request, _('الاسم المكتوب لا يطابق اسم الشركة، فلم يُحذف شيء.'))
        return _back(request)
    name = company.name
    purge.delete_company(company)  # the rows and the uploaded files
    messages.success(request, _('تم حذف اشتراك «%(name)s» وكل بياناته نهائياً.') % {'name': name})
    return redirect('ops:subscriptions')


@superuser_required
@require_POST
def subscription_login_as(request, pk):
    """Enter the subscriber's workspace as its owner (as in enjazpms); the admin's password is asked again."""
    company = get_object_or_404(Company, pk=pk)
    if not request.user.check_password(request.POST.get('password', '')):
        messages.error(request, _('كلمة مرور المشرف غير صحيحة.'))
        return _back(request)
    owner = subscriptions_service.owner(company)
    if owner is None or not owner.is_active:
        messages.error(request, _('لا يوجد مالك نشط لـ «%(name)s».') % {'name': company.name})
        return _back(request)
    admin_id = request.user.pk
    login(request, owner, backend='apps.accounts.backends.EmailOrUsernameBackend')  # starts a fresh session
    request.session[IMPERSONATOR_KEY] = admin_id
    request.session[COMPANY_SESSION_KEY] = company.pk
    return redirect('core:dashboard')


@superuser_required
def signups(request):
    """Self-registered accounts waiting for approval."""
    pending = User.objects.filter(is_approved=False, is_superuser=False).order_by('date_joined')
    return render(request, 'ops/signups.html', {'pending': pending})


@superuser_required
@require_POST
def signup_approve(request, pk):
    user = get_object_or_404(User, pk=pk, is_superuser=False)
    if user.is_approved:
        messages.info(request, _('حساب %(name)s مفعّل بالفعل.') % {'name': user.display_name})
    else:
        approval.approve(user)
        messages.success(request, _('تم تفعيل حساب %(name)s، وأُبلغ بالبريد.') % {'name': user.display_name})
    return redirect('ops:signups')


@superuser_required
@require_POST
def signup_reject(request, pk):
    user = get_object_or_404(User, pk=pk, is_approved=False, is_superuser=False)
    name = user.display_name
    user.delete()
    messages.success(request, _('تم رفض طلب %(name)s وحذفه.') % {'name': name})
    return redirect('ops:signups')


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
        'data': _subscription_data(company, owner, company.memberships.count(), company.posts.count(),
                                   catalog.money(charging.get_wallet(company).balance)),
        'edit_form': SubscriptionEditForm(),
        'members': company.memberships.select_related('user').order_by('created_at'),
        'plans': company.plans.annotate(n=Count('posts'))[:12],
        'posts_by_status': {Post.Status(s).label: n for s, n in
                            company.posts.order_by().values_list('status').annotate(n=Count('pk'))},
        'accounts': company.social_accounts.all(),
        'wallet': charging.get_wallet(company), 'wallet_amount': catalog.money(charging.get_wallet(company).balance),
        'wallet_rows': WalletTransaction.objects.filter(company=company)[:10],
        'revenue': charging.revenue(company=company),
        'current_operator': operator_names.bind(operators_service.of_company(company)),
        'operators_list': [operator_names.bind(o) for o in registry.operators(operators_service.PRODUCT)],
    })


@superuser_required
@require_POST
def wallet_grant(request, pk):
    """Add (or take back, with a minus) balance by hand: the way a company is funded until its operator's online payment is open."""
    from decimal import Decimal, InvalidOperation
    company = get_object_or_404(Company, pk=pk)
    try:
        amount = Decimal(request.POST.get('amount', ''))
        points = int(amount * catalog.POINTS_PER_RIYAL)
        if not points or abs(amount) > 5000 or amount != amount.to_integral_value():
            raise ValueError
    except (InvalidOperation, ValueError):
        messages.error(request, _('أدخل مبلغاً صحيحاً بالريال (حتى 5000).'))
        return _back_to(request, pk)
    charging.add_points(company, points, action=WalletTransaction.ADMIN_GRANT, user=request.user,
                        description=(request.POST.get('note') or '')[:200] or 'Admin grant')
    messages.success(request, _('تم تعديل الرصيد.'))
    return _back_to(request, pk)


@superuser_required
@require_POST
def wallet_exempt(request, pk):
    """An exempt company is never charged (the owner's own and demo companies)."""
    company = get_object_or_404(Company, pk=pk)
    wallet = charging.get_wallet(company)
    wallet.is_exempt = not wallet.is_exempt
    wallet.save(update_fields=['is_exempt'])
    messages.success(request, _('أصبحت الشركة معفاة من الخصم.') if wallet.is_exempt else _('أصبح الخصم من رصيد الشركة يعمل.'))
    return redirect('ops:company', pk=pk)


def _budget():
    from apps.credits import guards
    limit = Decimal(str(settings.AI_MONTHLY_BUDGET_USD))
    spent = guards.spend_this_month_usd()
    return {'limit': limit, 'spent': spent, 'percent': min(100, int(spent / limit * 100)) if limit > 0 else 0}


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
    by_model, by_kind = tables.breakdown('modelsTable', _('النموذج')), tables.breakdown('kindsTable', _('المهمة'))
    months_table, companies_table = tables.usage_months(), tables.usage_companies()
    return render(request, 'ops/usage.html', {
        'system': _system(), 'total': total, 'budget': _budget(),
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
    from .backup import last_status
    return render(request, 'ops/system.html', {
        'system': _system(),
        'backup': last_status(),
        'queue': {s: n for s, n in Job.objects.filter(status__in=[Job.Status.PENDING, Job.Status.RUNNING])
                  .order_by().values_list('status').annotate(n=Count('pk'))},
        'oldest_pending': Job.objects.filter(status=Job.Status.PENDING).order_by('created_at').first(),
    })


# ── Users, ledger, prices, activity, operators ───────────────────────────────

PAGE_SIZE = 50
PASSWORD_TRIES, PASSWORD_WINDOW = 5, 600


def _page(request, queryset):
    return Paginator(queryset, PAGE_SIZE).get_page(request.GET.get('page'))


def _password_ok(request) -> bool:
    """The superuser's own password, asked again before anything is deleted for good (a few tries, then a pause)."""
    key = f'ops-delete-fails-{request.user.pk}'
    fails = cache.get(key, 0)
    if fails >= PASSWORD_TRIES:
        messages.error(request, _('محاولات خاطئة كثيرة. حاول بعد دقائق. لم يُحذف شيء.'))
        return False
    if request.user.check_password(request.POST.get('password', '')):
        cache.delete(key)
        return True
    cache.set(key, fails + 1, PASSWORD_WINDOW)
    messages.error(request, _('كلمة المرور غير صحيحة. لم يُحذف شيء.'))
    return False


@superuser_required
def users(request):
    q = request.GET.get('q', '').strip()
    status = request.GET.get('status', '')
    queryset = User.objects.annotate(n_companies=Count('memberships')).order_by('-date_joined')
    if q:
        queryset = queryset.filter(Q(email__icontains=q) | Q(first_name__icontains=q) | Q(last_name__icontains=q))
    if status == 'inactive':
        queryset = queryset.filter(is_active=False)
    elif status == 'pending':
        queryset = queryset.filter(is_approved=False, is_superuser=False)
    elif status == 'superuser':
        queryset = queryset.filter(is_superuser=True)
    page = _page(request, queryset)
    owned = {}
    for m in (Membership.objects.filter(user__in=list(page), role=Membership.Role.OWNER)
              .select_related('company').order_by('company__name')):
        owned.setdefault(m.user_id, []).append(m.company)
    last_superuser = User.objects.filter(is_superuser=True).count() == 1
    for u in page:
        u.owned = owned.get(u.pk, [])
        u.last_superuser = last_superuser and u.is_superuser
    return render(request, 'ops/users.html', {'page': page, 'q': q, 'status': status})


@superuser_required
@require_POST
def user_toggle_active(request, pk):
    user = get_object_or_404(User, pk=pk)
    if user.pk == request.user.pk:
        messages.error(request, _('لا يمكنك تعطيل حسابك بنفسك.'))
        return redirect('ops:users')
    user.is_active = not user.is_active
    user.save(update_fields=['is_active'])
    messages.success(request, _('يستطيع %(email)s الدخول من جديد.') % {'email': user.email} if user.is_active
                     else _('لم يعد %(email)s يستطيع الدخول.') % {'email': user.email})
    return redirect('ops:users')


@superuser_required
@require_POST
def user_delete(request, pk):
    user = get_object_or_404(User, pk=pk)
    if user.is_superuser and User.objects.filter(is_superuser=True).count() == 1:
        messages.error(request, _('هذا آخر مشرف نظام فلا يُحذف.'))
        return redirect('ops:users')
    if not _password_ok(request):
        return redirect('ops:users')
    myself = user.pk == request.user.pk
    done = purge.delete_user(user)
    if myself:
        return redirect('admin:login')
    messages.success(request, _('حُذف %(email)s مع %(n)s شركة يملكها.') % {'email': done['email'], 'n': len(done['companies'])})
    return redirect('ops:users')


@superuser_required
def ledger(request):
    """Every movement of every wallet: top-ups, admin grants, AI sales and refunds."""
    q = request.GET.get('q', '').strip()
    action = request.GET.get('action', '')
    entries = WalletTransaction.objects.select_related('company', 'user').order_by('-created_at', '-id')
    only = Company.objects.filter(pk=request.GET['company']).first() if request.GET.get('company', '').isdigit() else None
    if only:
        entries = entries.filter(company=only)
    if action in dict(WalletTransaction.ACTION_CHOICES):
        entries = entries.filter(action=action)
    if q:
        entries = entries.filter(Q(company__name__icontains=q) | Q(user__email__icontains=q) | Q(description__icontains=q))
    month = timezone.now().replace(day=1, hour=0, minute=0, second=0, microsecond=0)
    month_rows = WalletTransaction.objects.filter(created_at__gte=month)
    topups = sum(month_rows.filter(action=WalletTransaction.TOPUP).values_list('delta', flat=True))
    grants = sum(month_rows.filter(action__in=[WalletTransaction.ADMIN_GRANT, WalletTransaction.TRIAL]).values_list('delta', flat=True))
    charged, refunded, net = charging.revenue(since=month)
    page = _page(request, entries)
    for t in page:
        t.amount = catalog.money(abs(t.delta))
    return render(request, 'ops/ledger.html', {
        'page': page, 'q': q, 'action': action, 'only': only, 'actions': WalletTransaction.ACTION_CHOICES,
        'month': {'topups': catalog.money(topups), 'grants': catalog.money(grants), 'charged': catalog.money(charged), 'net': catalog.money(net)},
    })


@superuser_required
def prices(request):
    """The price list as it is now (a draft until the owner settles it): what each service costs the customer."""
    from django.utils.translation import get_language
    lang = 'ar' if (get_language() or '').startswith('ar') else 'en'
    fixed = set(catalog.load().get('price_overrides') or {})
    rows = []
    for key in sorted(catalog.service_keys()):
        service = catalog.service(key)
        try:
            points = catalog.price_points(key) if not catalog.is_free(key) else 0
        except Exception:
            points = None
        rows.append({'key': key, 'name': catalog.service_name(key, lang), 'free': catalog.is_free(key),
                     'price': catalog.money(points) if points is not None else '—',
                     'per_page': bool(catalog.page_pricing(key)) and key not in fixed, 'launched': catalog.is_launched(key)})
    return render(request, 'ops/prices.html', {'rows': rows})


@superuser_required
def activity(request):
    """The activity log of every company (who opened, issued, shared, invited...), newest first."""
    from apps.audit.models import AuditEvent
    q = request.GET.get('q', '').strip()
    events = AuditEvent.all_companies.select_related('company').order_by('-created_at', '-id')
    if q:
        events = events.filter(Q(user_email__icontains=q) | Q(action__icontains=q) | Q(target__icontains=q) | Q(company__name__icontains=q))
    return render(request, 'ops/activity.html', {'page': _page(request, events), 'q': q})


@superuser_required
@require_POST
def company_operator(request, pk):
    """Move a company to another operator (the one that serves and bills it); its owner and admins are told."""
    from apps.companies import operators
    from apps.notifications.services import notify_event
    from enjaz_operators import registry
    company = get_object_or_404(Company, pk=pk)
    key = request.POST.get('operator', '')
    allowed = {o.key: o for o in registry.operators(operators.PRODUCT)}
    if key not in allowed:
        messages.error(request, _('مشغّل غير صالح.'))
        return redirect('ops:company', pk=pk)
    if key != operators.of_company(company).key:
        company.operator = key
        company.save(update_fields=['operator'])
        team = [m.user for m in company.memberships.select_related('user') if m.role in (Membership.Role.OWNER, Membership.Role.ADMIN)]
        notify_event(team, 'operator_changed', company=company, url='', operator=allowed[key].name('en'))
        messages.success(request, _('أصبحت الشركة تتبع «%(name)s».') % {'name': allowed[key].name('ar')})
    return redirect('ops:company', pk=pk)
