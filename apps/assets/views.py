import datetime
from collections import defaultdict
from decimal import Decimal

import secrets

from django.contrib import messages
from django.db.models import Q
from django.http import Http404, HttpResponse
from django.shortcuts import get_object_or_404, redirect, render
from django.urls import reverse
from django.utils import timezone
from django.utils.translation import gettext as _
from django.views.decorators.http import require_POST

from apps.audit import log as audit
from apps.audit.models import AuditEvent
from apps.companies.decorators import company_required

from . import checks, ical, importer, services
from .forms import AssetForm
from .models import SOON_DAYS, Asset, AssetCalendar, RenewalLog


def soon_limit():
    return timezone.localdate() + datetime.timedelta(days=SOON_DAYS)


@company_required
def asset_list(request):
    """The company's digital assets, soonest renewal first, with the totals of what they cost in a year."""
    everything = Asset.objects.select_related('responsible', 'document')
    kind = request.GET.get('kind', '')
    if kind not in dict(Asset.KINDS):
        kind = ''
    soon = request.GET.get('status') == 'soon'
    query = request.GET.get('q', '').strip()[:100]
    assets = everything
    if kind:
        assets = assets.filter(kind=kind)
    if soon:
        assets = assets.filter(expiry_date__isnull=False, expiry_date__lte=soon_limit())
    if query:
        assets = assets.filter(Q(name__icontains=query) | Q(provider__icontains=query) | Q(identifier__icontains=query) |
                               Q(account__icontains=query) | Q(notes__icontains=query))
    # Dated assets first (soonest on top), those without a renewal date after them.
    rows = sorted(assets, key=lambda a: (a.expiry_date is None, a.expiry_date or datetime.date.max, a.name.lower()))
    totals = defaultdict(Decimal)
    for asset in everything:
        if asset.yearly_cost is not None:
            totals[asset.currency] += asset.yearly_cost
    counts = {key: 0 for key, _label in Asset.KINDS}
    for asset in everything:
        counts[asset.kind] += 1
    statuses = [asset.status for asset in everything]
    return render(request, 'assets/list.html', {
        'assets': rows, 'kind': kind, 'soon': soon, 'q': query, 'count_all': sum(counts.values()),
        'late_count': statuses.count('expired'), 'soon_count': statuses.count('soon'),
        'kinds': [(key, label, Asset.ICONS[key], counts[key]) for key, label in Asset.KINDS],
        'expiring_here': everything.filter(expiry_date__isnull=False, expiry_date__lte=soon_limit()).count(),
        'yearly_totals': sorted(totals.items())})


def _form(request, asset, title):
    form = AssetForm(request.POST or None, instance=asset, company=request.company)
    if request.method == 'POST' and form.is_valid():
        saved = form.save(commit=False)
        saved.company = request.company
        new = saved.pk is None
        if new:
            saved.created_by = request.user
        if 'expiry_date' in form.changed_data:
            saved.reminded_days = None               # a renewal: the reminders start again for the new date
        saved.save()
        audit.record(request, AuditEvent.ASSET_CREATED if new else AuditEvent.ASSET_CHANGED, saved.name)
        messages.success(request, _('Saved.'))
        return redirect('assets:list')
    renewals = list(RenewalLog.objects.filter(asset=asset).select_related('by')[:12]) if asset.pk else []
    return render(request, 'assets/form.html', {'form': form, 'asset': asset, 'page_title': title, 'renewals': renewals})


@company_required(edit=True)
def new(request):
    kind = request.GET.get('kind')
    return _form(request, Asset(kind=kind if kind in dict(Asset.KINDS) else Asset.DOMAIN), _('Add a digital asset'))


@company_required(edit=True)
def edit(request, pk):
    return _form(request, get_object_or_404(Asset, pk=pk), _('Edit the digital asset'))


@company_required(edit=True)
@require_POST
def check(request, pk):
    """Read the domain's real end date now, from its registry."""
    asset = get_object_or_404(Asset, pk=pk)
    if not asset.checkable:
        messages.warning(request, _('Only a domain with its address can be checked automatically.'))
    elif checks.run(asset):
        messages.success(request, _('The end date was read: %(date)s.') % {'date': f'{asset.expiry_date:%Y-%m-%d}'})
    else:
        messages.error(request, asset.check_note or _('Could not read the end date.'))
    return redirect('assets:list')


@company_required(manage=True)
@require_POST
def delete(request, pk):
    asset = get_object_or_404(Asset, pk=pk)
    name = asset.name
    asset.delete()
    audit.record(request, AuditEvent.ASSET_DELETED, name)
    messages.success(request, _('Deleted.'))
    return redirect('assets:list')


@company_required(edit=True)
@require_POST
def renew(request, pk):
    """Mark the asset renewed: its date moves one cycle on, the reminders start again and the renewal goes in its history."""
    asset = get_object_or_404(Asset, pk=pk)
    try:
        services.renew(asset, request.user)
    except services.CannotRenew:
        messages.warning(request, _('This asset has no renewal date to move, or it is a one-time cost.'))
    else:
        audit.record(request, AuditEvent.ASSET_RENEWED, asset.name)
        messages.success(request, _('Renewed: the next renewal date is %(date)s.') % {'date': f'{asset.expiry_date:%Y-%m-%d}'})
    return redirect('assets:list')


@company_required(edit=True)
def import_csv(request):
    """Add many assets from a CSV file; the rows that are wrong are listed and skipped."""
    problems, saved = [], None
    if request.method == 'POST':
        upload = request.FILES.get('file')
        if upload is None:
            messages.error(request, _('Choose a file first.'))
        else:
            try:
                saved, problems = importer.read(upload, request.company)
            except importer.ImportFailed as exc:
                messages.error(request, str(exc))
            else:
                if saved:
                    audit.record(request, AuditEvent.ASSET_IMPORTED, f'{saved}')
                    messages.success(request, _('%(n)s assets were added.') % {'n': saved})
                if not saved and not problems:
                    messages.warning(request, _('The file has no rows to add.'))
    return render(request, 'assets/import.html', {'problems': problems[:30], 'more': max(0, len(problems) - 30), 'saved': saved,
                                                  'columns': importer.COLUMNS})


@company_required(edit=True)
def import_template(request):
    response = HttpResponse(importer.template_csv(), content_type='text/csv; charset=utf-8')
    response['Content-Disposition'] = 'attachment; filename="digital-assets-template.csv"'
    return response


@company_required(manage=True)
def calendar_page(request):
    """The address of the renewal calendar a phone can subscribe to; the manager can replace it when it should stop working."""
    feed = AssetCalendar.objects.first()
    if request.method == 'POST':
        token = secrets.token_urlsafe(24)
        if feed is None:
            feed = AssetCalendar(company=request.company)
        feed.token = token
        feed.save()
        audit.record(request, AuditEvent.ASSET_CALENDAR)
        messages.success(request, _('The calendar address is ready. The old one, if any, no longer works.'))
        return redirect('assets:calendar')
    url = request.build_absolute_uri(reverse('assets_public:feed', args=[feed.token])) if feed else ''
    return render(request, 'assets/calendar.html', {'feed_url': url, 'webcal_url': url.replace('https://', 'webcal://').replace('http://', 'webcal://')})


def public_feed(request, token):
    """The calendar feed itself: no login, the secret address is the key."""
    feed = AssetCalendar.all_companies.select_related('company').filter(token=token).first()
    if feed is None:
        raise Http404
    response = HttpResponse(ical.build(feed.company, host=request.get_host()), content_type='text/calendar; charset=utf-8')
    response['Cache-Control'] = 'private, no-store'
    response['X-Robots-Tag'] = 'noindex'
    return response
