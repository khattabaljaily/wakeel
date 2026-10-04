"""WhatsApp Business Cloud API (Meta): send template, image-with-buttons and text messages."""
import logging

import requests
from django.conf import settings
from django.utils.translation import gettext_lazy as _

logger = logging.getLogger(__name__)


class WhatsAppError(Exception):
    pass


def digits(phone):
    """'+974 5555-1234' -> '97455551234' (what the API uses for numbers)."""
    return ''.join(ch for ch in str(phone or '') if ch.isdigit()).lstrip('0')


def _send(to, payload):
    if not settings.WHATSAPP_ENABLED:
        raise WhatsAppError(_('واتساب غير مفعّل على هذا الخادم.'))
    url = f'https://graph.facebook.com/{settings.META_GRAPH_VERSION}/{settings.WHATSAPP_PHONE_NUMBER_ID}/messages'
    body = {'messaging_product': 'whatsapp', 'recipient_type': 'individual', 'to': digits(to), **payload}
    try:
        response = requests.post(url, json=body, headers={'Authorization': f'Bearer {settings.WHATSAPP_TOKEN}'}, timeout=30)
    except requests.RequestException as exc:
        raise WhatsAppError(_('تعذّر الوصول إلى خوادم واتساب.')) from exc
    try:
        data = response.json()
    except ValueError:
        data = {}
    if response.status_code >= 400 or 'error' in data:
        error = data.get('error') or {}
        logger.warning('WhatsApp API %s -> %s %s', payload.get('type'), response.status_code, error)
        detail = (error.get('error_data') or {}).get('details') or error.get('message') or response.status_code
        raise WhatsAppError(_('رفض واتساب الرسالة: %(detail)s') % {'detail': detail})
    return (data.get('messages') or [{}])[0].get('id', '')


def send_template(to, params, button_payload):
    """The approved review template: body variables {{1}}.. and one quick-reply button carrying `button_payload`."""
    return _send(to, {'type': 'template', 'template': {
        'name': settings.WHATSAPP_REVIEW_TEMPLATE,
        'language': {'code': settings.WHATSAPP_TEMPLATE_LANGUAGE},
        'components': [
            {'type': 'body', 'parameters': [{'type': 'text', 'text': str(p)[:1000]} for p in params]},
            {'type': 'button', 'sub_type': 'quick_reply', 'index': '0', 'parameters': [{'type': 'payload', 'payload': button_payload}]},
        ],
    }})


def send_image_buttons(to, image_url, body, buttons):
    """An image with text under it and up to three reply buttons [(id, title)]."""
    return _send(to, {'type': 'interactive', 'interactive': {
        'type': 'button',
        'header': {'type': 'image', 'image': {'link': image_url}},
        'body': {'text': str(body)[:1024]},
        'action': {'buttons': [{'type': 'reply', 'reply': {'id': bid, 'title': str(title)[:20]}} for bid, title in buttons[:3]]},
    }})


def send_buttons(to, body, buttons):
    return _send(to, {'type': 'interactive', 'interactive': {
        'type': 'button', 'body': {'text': str(body)[:1024]},
        'action': {'buttons': [{'type': 'reply', 'reply': {'id': bid, 'title': str(title)[:20]}} for bid, title in buttons[:3]]},
    }})


def send_text(to, text):
    return _send(to, {'type': 'text', 'text': {'body': str(text)[:4096], 'preview_url': True}})
