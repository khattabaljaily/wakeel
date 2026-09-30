"""Web Push: send a user's in-app notifications to their phones and browsers too.

Sending happens on a background thread so a notification never slows the request that caused it.
Subscriptions that the push service reports as gone (404/410) are deleted.
"""
import json
import logging
import threading

from django.conf import settings
from django.db import close_old_connections
from django.utils import timezone

logger = logging.getLogger(__name__)


def enabled():
    return bool(settings.VAPID_PUBLIC_KEY and settings.VAPID_PRIVATE_KEY)


def send(users, *, title, body, url='', tag=''):
    """Queue a push to every subscribed device of these users."""
    if not enabled():
        return
    user_ids = [u.pk for u in users if u is not None]
    if not user_ids:
        return
    payload = json.dumps({'title': title, 'body': body[:240], 'url': url or '/app/', 'tag': tag}, ensure_ascii=False)
    if settings.PUSH_IN_BACKGROUND:
        threading.Thread(target=_deliver, args=(user_ids, payload), daemon=True).start()
    else:
        _deliver(user_ids, payload)


def _deliver(user_ids, payload):
    from py_vapid import Vapid01
    from pywebpush import WebPushException, webpush

    from .models import PushSubscription

    try:
        vapid = Vapid01.from_string(settings.VAPID_PRIVATE_KEY)
        for sub in PushSubscription.objects.filter(user_id__in=user_ids):
            try:
                webpush(sub.as_info(), payload, vapid_private_key=vapid,
                        vapid_claims={'sub': settings.VAPID_SUBJECT}, ttl=24 * 3600, timeout=10)
                PushSubscription.objects.filter(pk=sub.pk).update(last_sent_at=timezone.now())
            except WebPushException as exc:
                status = getattr(exc.response, 'status_code', None)
                if status in (404, 410):  # the device unsubscribed or the browser dropped it
                    sub.delete()
                else:
                    logger.warning('Push to subscription %s failed: %s', sub.pk, exc)
            except Exception:
                logger.exception('Push to subscription %s failed', sub.pk)
    finally:
        if settings.PUSH_IN_BACKGROUND:
            close_old_connections()
