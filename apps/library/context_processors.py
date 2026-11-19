import datetime

from django.utils import timezone

from .models import SOON_DAYS, Record


def library_alerts(request):
    """How many papers have expired or expire within SOON_DAYS: the badge on the documents link in the side menu."""
    company = getattr(request, 'company', None)
    if company is None or not request.user.is_authenticated or request.user.is_superuser:
        return {}
    soon = timezone.localdate() + datetime.timedelta(days=SOON_DAYS)
    return {'library_alerts': Record.objects.for_company(company).filter(expiry_date__isnull=False,
                                                                           expiry_date__lte=soon).count()}
