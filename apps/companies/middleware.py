from django.utils import timezone

from apps.core.tenancy import reset_current_company, set_current_company

from .models import Membership

SESSION_KEY = 'wakeel_company_id'


class CurrentCompanyMiddleware:
    """Attach the company the user is working in (and their membership) to the request and as the
    company context that scopes `CompanyScopedModel` queries.

    The choice lives in the session; if it's missing or no longer valid we fall
    back to the user's first company. The company's timezone is activated so
    every date shown or entered in the app is in the company's local time.
    """

    def __init__(self, get_response):
        self.get_response = get_response

    def __call__(self, request):
        request.company = None
        request.membership = None
        if request.user.is_authenticated:
            memberships = Membership.objects.filter(user=request.user).select_related('company')
            wanted = request.session.get(SESSION_KEY)
            membership = None
            if wanted:
                membership = memberships.filter(company_id=wanted).first()
            if membership is None:
                membership = memberships.order_by('created_at').first()
                if membership:
                    request.session[SESSION_KEY] = membership.company_id
            if membership:
                request.membership = membership
                request.company = membership.company
                timezone.activate(membership.company.tzinfo)
        token = set_current_company(request.company)
        try:
            return self.get_response(request)
        finally:
            reset_current_company(token)
            timezone.deactivate()
