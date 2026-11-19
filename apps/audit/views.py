from django.core.paginator import Paginator
from django.shortcuts import render

from apps.companies.decorators import company_required

from .models import AuditEvent


@company_required(manage=True)
def activity(request):
    """Who did what with documents, the company mailbox and the team. For owners and admins."""
    page = Paginator(AuditEvent.objects.all(), 50).get_page(request.GET.get('page'))
    return render(request, 'audit/activity.html', {'page': page})
