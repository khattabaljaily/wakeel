import logging

from django.conf import settings

from .models import Notification
from .registry import COLLECTORS

logger = logging.getLogger(__name__)


def notifications(request):
    """The bell in the top bar. First the collectors run, so whatever is due (a reminder whose time came) is in the list the
    member sees now, without waiting for a scheduled job."""
    if not getattr(request, 'user', None) or not request.user.is_authenticated:
        return {}
    company = getattr(request, 'company', None)
    if company is not None:
        for collect in COLLECTORS:
            try:
                collect(request.user, company)
            except Exception:
                logger.exception('A notification collector failed')
    unread = Notification.objects.filter(user=request.user, read_at__isnull=True)
    return {
        'unread_notifications': unread.count(),
        'recent_notifications': Notification.objects.filter(user=request.user).select_related('company')[:8],
        'vapid_public_key': settings.VAPID_PUBLIC_KEY,
    }
