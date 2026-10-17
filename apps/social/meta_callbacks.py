"""Meta's deauthorize and data-deletion callbacks (required for a Live app; both are POSTed a signed_request).

Meta names only the app-scoped user id, so the accounts to remove are found by SocialAccount.meta_user_id,
which is saved when the person connects. Accounts connected before that field existed can be removed
by the person themselves (Publishing accounts → disconnect) or on request by email.
"""
import base64
import hashlib
import hmac
import json
import logging
import secrets

from django.conf import settings
from django.http import Http404, HttpResponseBadRequest, JsonResponse
from django.shortcuts import render
from django.utils.translation import gettext_lazy as _
from django.views.decorators.csrf import csrf_exempt

from apps.core.views import _public_page

from .models import MetaDeletionRequest, SocialAccount

logger = logging.getLogger(__name__)
META_PLATFORMS = [SocialAccount.Platform.FACEBOOK, SocialAccount.Platform.INSTAGRAM]


def parse_signed_request(signed_request, secret):
    """The payload of a Meta signed_request ('signature.payload', base64url), or None if it isn't signed by `secret`."""
    try:
        sig, payload = signed_request.split('.', 1)
        expected = hmac.new(secret.encode(), payload.encode(), hashlib.sha256).digest()
        if not hmac.compare_digest(_b64decode(sig), expected):
            return None
        data = json.loads(_b64decode(payload))
    except (ValueError, AttributeError, TypeError):
        return None
    if not isinstance(data, dict) or str(data.get('algorithm', '')).upper() != 'HMAC-SHA256':
        return None
    return data


def _b64decode(value):
    return base64.urlsafe_b64decode(value + '=' * (-len(value) % 4))


def _user_id(request):
    """The verified Meta user id of a callback, or None."""
    if not settings.META_APP_SECRET:
        return None
    data = parse_signed_request(request.POST.get('signed_request', ''), settings.META_APP_SECRET)
    user_id = str((data or {}).get('user_id') or '')
    return user_id or None


def _remove_accounts(user_id):
    deleted, _rows = SocialAccount.objects.filter(platform__in=META_PLATFORMS, meta_user_id=user_id).delete()
    return deleted


@csrf_exempt
def deauthorize(request):
    """The person removed Wakeel in their Facebook settings: forget their tokens."""
    if request.method != 'POST':
        return HttpResponseBadRequest()
    user_id = _user_id(request)
    if not user_id:
        return HttpResponseBadRequest('invalid signed_request')
    logger.info('Meta deauthorize: removed %s account(s) of user %s', _remove_accounts(user_id), user_id)
    return JsonResponse({'success': True})


@csrf_exempt
def data_deletion(request):
    """POST: Meta's deletion request, answered with the status URL and a confirmation code. GET: the instructions page."""
    if request.method == 'GET':
        return _public_page(request, 'core/legal.html', 'data_deletion', page_title=_('حذف البيانات'),
                            page_icon='bi-trash3', page_lead=_('كيف تحذف بياناتك من وكيل، بما فيها ما وصلنا من فيسبوك وإنستغرام.'))
    if request.method != 'POST':
        return HttpResponseBadRequest()
    user_id = _user_id(request)
    if not user_id:
        return HttpResponseBadRequest('invalid signed_request')
    record = MetaDeletionRequest.objects.create(code=secrets.token_hex(8), meta_user_id=user_id,
                                                accounts_deleted=_remove_accounts(user_id))
    logger.info('Meta data deletion %s: removed %s account(s) of user %s', record.code, record.accounts_deleted, user_id)
    return JsonResponse({'url': f'{settings.SITE_URL.rstrip("/")}/meta/data-deletion/status/{record.code}/',
                         'confirmation_code': record.code})


def deletion_status(request, code):
    record = MetaDeletionRequest.objects.filter(code=code).first()
    if record is None:
        raise Http404
    return render(request, 'social/deletion_status.html', {'record': record})
