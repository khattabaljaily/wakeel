import secrets

from django.conf import settings
from django.contrib import messages
from django.shortcuts import get_object_or_404, redirect, render
from django.urls import reverse
from django.utils.translation import gettext_lazy as _
from django.views.decorators.http import require_POST

from apps.companies.decorators import company_required

from .meta import MetaError, login_url, pages_for_code
from .models import SocialAccount

STATE_KEY = 'wakeel_meta_state'
PAGES_KEY = 'wakeel_meta_pages'
RESULT_KEY = 'wakeel_meta_result'

# The setup wizard: each step belongs to one of the four stages shown in its progress bar.
SETUP_STEPS = {'page': 0, 'page-create': 0, 'instagram': 1, 'ig-pro': 1, 'ig-link': 1, 'connect': 2, 'result': 3}


def _redirect_uri():
    return settings.SITE_URL + reverse('social:meta_callback')


@company_required(manage=True)
def accounts(request):
    return render(request, 'social/accounts.html', {
        'accounts': {a.platform: a for a in SocialAccount.objects.filter(company=request.company)},
        'meta_enabled': settings.META_ENABLED, 'redirect_uri': _redirect_uri(),
    })


@company_required(manage=True)
def setup(request):
    """Walks the subscriber through getting a Page (and Instagram) ready, then connecting them in a popup."""
    step = request.GET.get('step')
    if step not in SETUP_STEPS:
        step = 'page'
    accounts = {a.platform: a for a in SocialAccount.objects.filter(company=request.company)}
    result = None
    if step == 'result':
        result = request.session.pop(RESULT_KEY, None)
        if result is None:  # the window closed without finishing, or the page was reloaded
            result = 'cancelled' if request.GET.get('closed') or 'facebook' not in accounts else 'connected'
        if result == 'connected' and 'instagram' not in accounts:
            result = 'no-instagram'
    stage = SETUP_STEPS[step]
    return render(request, 'social/setup.html', {
        'step': step, 'stage': stage, 'progress': stage / 3, 'result': result, 'accounts': accounts,
        'meta_enabled': settings.META_ENABLED,
    })


@company_required(manage=True)
@require_POST
def meta_connect(request):
    if not settings.META_ENABLED:
        messages.error(request, _('ربط فيسبوك وإنستغرام غير متاح حالياً. تواصل مع الدعم لتفعيله.'))
        return redirect('social:accounts')
    state = secrets.token_urlsafe(24)
    request.session[STATE_KEY] = {'state': state, 'company': request.company.pk, 'popup': request.POST.get('popup') == '1'}
    request.session.pop(RESULT_KEY, None)
    return redirect(login_url(_redirect_uri(), state))


def _finish(request, result, popup):
    """End a connection attempt: the wizard's result step shows what happened and what to do next."""
    request.session[RESULT_KEY] = result
    if popup:  # tell the wizard in the opener window, then close
        return render(request, 'social/popup_done.html', {'result_url': reverse('social:setup') + '?step=result'})
    return redirect(reverse('social:setup') + '?step=result')


@company_required(manage=True)
def meta_callback(request):
    expected = request.session.pop(STATE_KEY, None) or {}
    popup = expected.get('popup', False)
    if not expected or request.GET.get('state') != expected.get('state') or expected.get('company') != request.company.pk:
        messages.error(request, _('انتهت جلسة الربط أو لا تخص هذه الشركة. حاول مرة أخرى.'))
        return _finish(request, 'error', popup)
    if 'error' in request.GET or 'code' not in request.GET:
        return _finish(request, 'cancelled', popup)
    try:
        pages = pages_for_code(request.GET['code'], _redirect_uri())
    except MetaError as exc:
        messages.error(request, str(exc))
        return _finish(request, 'error', popup)
    if not pages:
        return _finish(request, 'no-pages', popup)
    request.session[PAGES_KEY] = {'company': request.company.pk, 'pages': pages, 'popup': popup}
    if len(pages) == 1:
        return _connect(request, pages[0], popup)
    return render(request, 'social/choose_page.html', {
        'pages': pages, 'layout': 'social/popup_base.html' if popup else 'base.html',
    })


@company_required(manage=True)
@require_POST
def meta_choose(request):
    stored = request.session.get(PAGES_KEY) or {}
    page = next((p for p in stored.get('pages', []) if p['id'] == request.POST.get('page')), None)
    if stored.get('company') != request.company.pk or page is None:
        messages.error(request, _('انتهت جلسة الربط. حاول مرة أخرى.'))
        return _finish(request, 'error', stored.get('popup', False))
    return _connect(request, page, stored.get('popup', False))


def _connect(request, page, popup):
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
        return _finish(request, 'connected', popup)
    SocialAccount.objects.filter(company=company, platform=SocialAccount.Platform.INSTAGRAM).delete()
    return _finish(request, 'no-instagram', popup)


@company_required(manage=True)
@require_POST
def disconnect(request, platform):
    get_object_or_404(SocialAccount, company=request.company, platform=platform).delete()
    messages.success(request, _('تم فصل الحساب.'))
    return redirect('social:accounts')


@company_required(manage=True)
@require_POST
def auto_publish(request):
    request.company.auto_publish = request.POST.get('auto_publish') == 'on'
    request.company.save(update_fields=['auto_publish'])
    messages.success(request, _('تم تفعيل النشر التلقائي.') if request.company.auto_publish else _('تم إيقاف النشر التلقائي.'))
    return redirect('social:accounts')
