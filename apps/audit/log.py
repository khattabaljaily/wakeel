"""`record(request, action, target, **detail)`: write one audit event for the active company."""
import logging

from django.conf import settings

from .models import AuditEvent

logger = logging.getLogger(__name__)


def client_ip(request):
    """The visitor's address. Behind our proxy (Cloudflare and Nginx) the real one is in a header; without a proxy the
    header could be forged by the visitor, so it is trusted only when secrets.json says we are behind one."""
    if getattr(settings, 'USE_X_FORWARDED_HOST', False):
        forwarded = request.META.get('HTTP_CF_CONNECTING_IP') or request.META.get('HTTP_X_FORWARDED_FOR', '').split(',')[0]
        if forwarded.strip():
            return forwarded.strip()
    return request.META.get('REMOTE_ADDR') or None


def record(request, action, target='', company=None, **detail):
    """Never raises: the log must not break the action it describes."""
    try:
        user = request.user if request.user.is_authenticated else None
        AuditEvent.all_companies.create(
            company=company or request.company, user=user, user_email=getattr(user, 'email', '') or '',
            action=action, target=str(target)[:200], detail=detail, ip=client_ip(request))
    except Exception:
        logger.exception('Could not write the audit event %s', action)
