from .models import Notification


def notifications(request):
    if not getattr(request, 'user', None) or not request.user.is_authenticated:
        return {}
    unread = Notification.objects.filter(user=request.user, read_at__isnull=True)
    return {
        'unread_notifications': unread.count(),
        'recent_notifications': Notification.objects.filter(user=request.user).select_related('company')[:8],
    }
