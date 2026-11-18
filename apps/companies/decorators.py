from functools import wraps

from django.contrib import messages
from django.contrib.auth.decorators import login_required
from django.core.exceptions import PermissionDenied
from django.shortcuts import redirect
from django.utils.translation import gettext_lazy as _

from .models import Membership


def company_required(view=None, *, manage=False, edit=False, client=False):
    """Require a logged-in user working inside a company.

    Users with no company yet are sent to the onboarding wizard. `edit` needs a
    non-viewer role, `manage` needs owner/admin. An outside client of the company (Membership.Role.CLIENT) is refused unless the
    view says `client=True`: the company's papers, team, marketing and inbox are not theirs to read, so a new page is closed to them
    by default and only the few they use (dashboard, personal notes) open the door.
    """

    def decorator(fn):
        @login_required
        @wraps(fn)
        def wrapped(request, *args, **kwargs):
            if request.user.is_superuser:
                # System admins have their own console; subscriber pages are for subscribers.
                return redirect('ops:overview')
            if request.company is None:
                return redirect('companies:create')
            if not request.company.is_usable:
                # Awaiting approval, suspended or expired: the status page explains.
                return redirect('companies:status')
            if request.membership.role == Membership.Role.CLIENT and not client:
                raise PermissionDenied
            if manage and not request.membership.can_manage:
                raise PermissionDenied
            if edit and not request.membership.can_edit:
                messages.error(request, _('صلاحيتك في هذه الشركة للمشاهدة فقط.'))
                return redirect('core:dashboard')
            return fn(request, *args, **kwargs)
        return wrapped

    return decorator(view) if view else decorator
