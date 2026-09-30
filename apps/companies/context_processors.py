from django.conf import settings

from .models import Membership


def current_company(request):
    if not getattr(request, 'user', None) or not request.user.is_authenticated:
        return {}
    return {
        # A system admin working inside this account from the console (see ops.views.subscription_login_as).
        'impersonating': bool(request.session.get('_impersonator_id')),
        'ai_enabled': settings.AI_ENABLED,
        'ai_key_name': settings.AI_KEY_NAME,
        'company': getattr(request, 'company', None),
        'membership': getattr(request, 'membership', None),
        'my_memberships': Membership.objects.filter(user=request.user).select_related('company').order_by('company__name'),
    }
