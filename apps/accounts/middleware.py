from django.http import JsonResponse
from django.shortcuts import redirect
from django.utils.translation import gettext_lazy as _

# What an account awaiting approval may still reach.
ALLOWED_PREFIXES = ('/accounts/', '/static/', '/media/', '/i18n/', '/sw.js', '/manifest.webmanifest', '/offline/', '/jsi18n/')


class PendingAccountMiddleware:
    """Keep self-registered accounts on the 'under review' page until a system admin approves them."""

    def __init__(self, get_response):
        self.get_response = get_response

    def __call__(self, request):
        user = request.user
        if (user.is_authenticated and not user.is_superuser and not user.is_approved
                and not request.path.startswith(ALLOWED_PREFIXES)):
            if request.path.startswith('/api/'):
                return JsonResponse({'error': _('حسابك قيد المراجعة.')}, status=403)
            return redirect('accounts:pending')
        return self.get_response(request)
