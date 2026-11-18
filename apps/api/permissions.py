from rest_framework.permissions import BasePermission
from django.utils.translation import gettext_lazy as _

from apps.companies.models import Membership


class InCompany(BasePermission):
    """The user is working inside a company; writes need a non-viewer role."""

    message = _('لا تملك صلاحية تنفيذ هذا الإجراء في هذه الشركة.')

    def has_permission(self, request, view):
        membership = getattr(request._request, 'membership', None)
        if membership is None or not membership.company.is_usable:
            return False
        if membership.role == Membership.Role.CLIENT:      # an outside client reads nothing of the company's work through the API either
            return False
        if request.method in ('GET', 'HEAD', 'OPTIONS'):
            return True
        return membership.can_edit


class InCompanyAnyRole(BasePermission):
    """The user is working inside a company, whatever their role (viewers included)."""

    message = InCompany.message

    def has_permission(self, request, view):
        membership = getattr(request._request, 'membership', None)
        return (membership is not None and membership.company.is_usable and membership.role != Membership.Role.CLIENT)
