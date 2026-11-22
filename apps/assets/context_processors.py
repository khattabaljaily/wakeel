from .models import Asset
from .views import soon_limit


def asset_alerts(request):
    """How many assets have to be renewed within SOON_DAYS (or are late): the badge on the assets link in the side menu."""
    company = getattr(request, 'company', None)
    if company is None or not request.user.is_authenticated or request.user.is_superuser:
        return {}
    return {'asset_alerts': Asset.objects.for_company(company).filter(expiry_date__isnull=False,
                                                                       expiry_date__lte=soon_limit()).count()}
