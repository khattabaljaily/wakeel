from rest_framework.permissions import BasePermission


class InCompany(BasePermission):
    """The user is working inside a company; writes need a non-viewer role."""

    message = 'لا تملك صلاحية تنفيذ هذا الإجراء في هذه الشركة.'

    def has_permission(self, request, view):
        membership = getattr(request._request, 'membership', None)
        if membership is None:
            return False
        if request.method in ('GET', 'HEAD', 'OPTIONS'):
            return True
        return membership.can_edit
