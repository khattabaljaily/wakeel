import json

from django.contrib.auth.decorators import login_required
from django.core.paginator import Paginator
from django.http import JsonResponse
from django.shortcuts import get_object_or_404, redirect, render
from django.utils import timezone
from django.utils.http import url_has_allowed_host_and_scheme
from django.views.decorators.http import require_POST

from apps.companies.middleware import SESSION_KEY

from .models import Notification, PushSubscription


@login_required
def notification_list(request):
    notes = Notification.objects.filter(user=request.user).select_related('company')
    page = Paginator(notes, 30).get_page(request.GET.get('page'))
    return render(request, 'notifications/list.html', {'page': page})


@login_required
def notification_open(request, pk):
    note = get_object_or_404(Notification, pk=pk, user=request.user)
    if note.read_at is None:
        note.read_at = timezone.now()
        note.save(update_fields=['read_at'])
    # The notification may belong to another of the user's companies; switch to it first.
    if request.user.memberships.filter(company_id=note.company_id).exists():
        request.session[SESSION_KEY] = note.company_id
    if note.url and url_has_allowed_host_and_scheme(note.url, allowed_hosts={request.get_host()}):
        return redirect(note.url)
    return redirect('notifications:list')


@login_required
@require_POST
def notification_read_all(request):
    Notification.objects.filter(user=request.user, read_at__isnull=True).update(read_at=timezone.now())
    return redirect(request.POST.get('next') or 'notifications:list')


@login_required
@require_POST
def push_subscribe(request):
    """Register this browser/device for push notifications (the page sends the PushSubscription JSON)."""
    try:
        data = json.loads(request.body or b'{}')
        endpoint, keys = data['endpoint'], data['keys']
        p256dh, auth = keys['p256dh'], keys['auth']
    except (ValueError, KeyError, TypeError):
        return JsonResponse({'error': 'اشتراك غير صالح.'}, status=400)
    if not str(endpoint).startswith('https://') or len(endpoint) > 2000:
        return JsonResponse({'error': 'اشتراك غير صالح.'}, status=400)
    PushSubscription.objects.update_or_create(endpoint_hash=PushSubscription.hash(endpoint), defaults={
        'endpoint': endpoint, 'user': request.user, 'p256dh': p256dh[:200], 'auth': auth[:100],
        'user_agent': request.META.get('HTTP_USER_AGENT', '')[:300]})
    return JsonResponse({'ok': True})


@login_required
@require_POST
def push_unsubscribe(request):
    try:
        endpoint = json.loads(request.body or b'{}').get('endpoint', '')
    except ValueError:
        endpoint = ''
    PushSubscription.objects.filter(user=request.user, endpoint_hash=PushSubscription.hash(endpoint)).delete()
    return JsonResponse({'ok': True})
