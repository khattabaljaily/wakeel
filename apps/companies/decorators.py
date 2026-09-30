from functools import wraps

from django.contrib import messages
from django.contrib.auth.decorators import login_required
from django.core.exceptions import PermissionDenied
from django.shortcuts import redirect


def company_required(view=None, *, manage=False, edit=False):
    """Require a logged-in user working inside a company.

    Users with no company yet are sent to the onboarding wizard. `edit` needs a
    non-viewer role, `manage` needs owner/admin.
    """

    def decorator(fn):
        @login_required
        @wraps(fn)
        def wrapped(request, *args, **kwargs):
            if request.company is None:
                return redirect('companies:create')
            if manage and not request.membership.can_manage:
                raise PermissionDenied
            if edit and not request.membership.can_edit:
                messages.error(request, 'صلاحيتك في هذه الشركة للمشاهدة فقط.')
                return redirect('core:dashboard')
            return fn(request, *args, **kwargs)
        return wrapped

    return decorator(view) if view else decorator
