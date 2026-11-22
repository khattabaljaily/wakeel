import datetime
from collections import defaultdict
from decimal import Decimal

from django.contrib import messages
from django.db.models import Q
from django.shortcuts import get_object_or_404, redirect, render
from django.utils import timezone
from django.utils.translation import gettext as _
from django.views.decorators.http import require_POST

from apps.audit import log as audit
from apps.audit.models import AuditEvent
from apps.companies.decorators import company_required

from . import checks
from .forms import AssetForm
from .models import SOON_DAYS, Asset


def soon_limit():
    return timezone.localdate() + datetime.timedelta(days=SOON_DAYS)


@company_required
def asset_list(request):
    """The company's digital assets, soonest renewal first, with the totals of what they cost in a year."""
    everything = Asset.objects.select_related('responsible')
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
    return render(request, 'assets/form.html', {'form': form, 'asset': asset, 'page_title': title})


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
