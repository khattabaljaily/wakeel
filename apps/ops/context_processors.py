import datetime

from django.utils import timezone

from apps.companies.models import Company
from apps.jobs.models import Job


def ops(request):
    """Badges for the superuser sidebar."""
    user = getattr(request, 'user', None)
    if not user or not user.is_authenticated or not user.is_superuser:
        return {}
    week_ago = timezone.now() - datetime.timedelta(days=7)
    return {
        'ops_failed_week': Job.objects.filter(status=Job.Status.FAILED, created_at__gte=week_ago).count(),
        'ops_pending_approval': Company.objects.filter(is_approved=False).count(),
    }
