import secrets

from django.conf import settings
from django.contrib import messages
from django.shortcuts import get_object_or_404, redirect, render
from django.urls import reverse
from django.views.decorators.http import require_POST

from apps.companies.decorators import company_required

from .meta import MetaError, login_url, pages_for_code
from .models import SocialAccount

STATE_KEY = 'wakeel_meta_state'
PAGES_KEY = 'wakeel_meta_pages'


def _redirect_uri():
    return settings.SITE_URL + reverse('social:meta_callback')


@company_required(manage=True)
def accounts(request):
    return render(request, 'social/accounts.html', {
        'accounts': {a.platform: a for a in SocialAccount.objects.filter(company=request.company)},
        'meta_enabled': settings.META_ENABLED, 'redirect_uri': _redirect_uri(),
    })


@company_required(manage=True)
@require_POST
def meta_connect(request):
    if not settings.META_ENABLED:
        messages.error(request, 'ربط فيسبوك وإنستغرام غير متاح حالياً. تواصل مع الدعم لتفعيله.')
        return redirect('social:accounts')
    state = secrets.token_urlsafe(24)
    request.session[STATE_KEY] = {'state': state, 'company': request.company.pk}
    return redirect(login_url(_redirect_uri(), state))


@company_required(manage=True)
def meta_callback(request):
    expected = request.session.pop(STATE_KEY, None) or {}
    if not expected or request.GET.get('state') != expected.get('state') or expected.get('company') != request.company.pk:
        messages.error(request, 'انتهت جلسة الربط أو لا تخص هذه الشركة. حاول مرة أخرى.')
        return redirect('social:accounts')
    if 'error' in request.GET or 'code' not in request.GET:
        messages.info(request, 'أُلغي ربط الحساب.')
        return redirect('social:accounts')
    try:
        pages = pages_for_code(request.GET['code'], _redirect_uri())
    except MetaError as exc:
        messages.error(request, str(exc))
        return redirect('social:accounts')
    if not pages:
        messages.error(request, 'لم نجد صفحات فيسبوك تديرها بهذا الحساب، أو لم تُمنح صلاحية الوصول إليها.')
        return redirect('social:accounts')
    request.session[PAGES_KEY] = {'company': request.company.pk, 'pages': pages}
    if len(pages) == 1:
        return _connect(request, pages[0])
    return render(request, 'social/choose_page.html', {'pages': pages})


@company_required(manage=True)
@require_POST
def meta_choose(request):
    stored = request.session.get(PAGES_KEY) or {}
    page = next((p for p in stored.get('pages', []) if p['id'] == request.POST.get('page')), None)
    if stored.get('company') != request.company.pk or page is None:
        messages.error(request, 'انتهت جلسة الربط. حاول مرة أخرى.')
        return redirect('social:accounts')
    return _connect(request, page)


def _connect(request, page):
    request.session.pop(PAGES_KEY, None)
    company = request.company
    SocialAccount.objects.update_or_create(company=company, platform=SocialAccount.Platform.FACEBOOK, defaults={
        'external_id': page['id'], 'name': page['name'], 'access_token': page['token'],
        'connected_by': request.user, 'last_error': '',
    })
    ig = page.get('instagram') or {}
    if ig.get('id'):
        SocialAccount.objects.update_or_create(company=company, platform=SocialAccount.Platform.INSTAGRAM, defaults={
            'external_id': ig['id'], 'name': ig.get('username') or page['name'], 'access_token': page['token'],
            'connected_by': request.user, 'last_error': '',
        })
        messages.success(request, f'تم ربط صفحة «{page["name"]}» وحساب إنستغرام @{ig.get("username", "")}.')
    else:
        SocialAccount.objects.filter(company=company, platform=SocialAccount.Platform.INSTAGRAM).delete()
        messages.success(request, f'تم ربط صفحة «{page["name"]}». لا يوجد حساب إنستغرام احترافي مرتبط بهذه الصفحة.')
    return redirect('social:accounts')


@company_required(manage=True)
@require_POST
def disconnect(request, platform):
    get_object_or_404(SocialAccount, company=request.company, platform=platform).delete()
    messages.success(request, 'تم فصل الحساب.')
    return redirect('social:accounts')


@company_required(manage=True)
@require_POST
def auto_publish(request):
    request.company.auto_publish = request.POST.get('auto_publish') == 'on'
    request.company.save(update_fields=['auto_publish'])
    messages.success(request, 'تم تفعيل النشر التلقائي.' if request.company.auto_publish else 'تم إيقاف النشر التلقائي.')
    return redirect('social:accounts')
