import hashlib
import hmac
import json
import logging

from django.conf import settings
from django.contrib import messages
from django.http import HttpResponse, HttpResponseForbidden
from django.shortcuts import get_object_or_404, redirect
from django.utils.translation import gettext_lazy as _
from django.views.decorators.csrf import csrf_exempt
from django.views.decorators.http import require_POST

from apps.companies.decorators import company_required
from apps.content.models import ContentPlan

from . import services
from .client import WhatsAppError

logger = logging.getLogger(__name__)


@csrf_exempt
def webhook(request):
    """Meta's webhook: GET verifies the subscription, POST delivers messages (signed with the app secret)."""
    if request.method == 'GET':
        if (request.GET.get('hub.mode') == 'subscribe' and settings.WHATSAPP_VERIFY_TOKEN
                and hmac.compare_digest(request.GET.get('hub.verify_token', ''), settings.WHATSAPP_VERIFY_TOKEN)):
            return HttpResponse(request.GET.get('hub.challenge', ''), content_type='text/plain')
        return HttpResponseForbidden()
    if request.method != 'POST' or not settings.WHATSAPP_APP_SECRET:
        return HttpResponseForbidden()
    expected = 'sha256=' + hmac.new(settings.WHATSAPP_APP_SECRET.encode(), request.body, hashlib.sha256).hexdigest()
    if not hmac.compare_digest(request.headers.get('X-Hub-Signature-256', ''), expected):
        return HttpResponseForbidden()
    try:
        payload = json.loads(request.body or b'{}')
    except json.JSONDecodeError:
        return HttpResponse(status=400)
    try:
        services.handle_payload(payload)
    except Exception:  # Meta retries on errors; one bad message must not cause a retry storm
        logger.exception('WhatsApp webhook failed')
    return HttpResponse('ok')


@company_required(manage=True)
@require_POST
def send_plan(request, pk):
    plan = get_object_or_404(ContentPlan, pk=pk, company=request.company, status=ContentPlan.Status.READY)
    try:
        services.invite(plan)
    except WhatsAppError as exc:
        messages.error(request, str(exc))
    else:
        messages.success(request, _('أُرسلت دعوة المراجعة إلى واتساب العميل.'))
    return redirect(plan.get_absolute_url() + '#share')
