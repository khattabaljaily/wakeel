from django.core.paginator import Paginator
from django.shortcuts import render

from apps.companies.decorators import company_required

from apps.billing.gateways import payments_open

from . import catalog
from .charging import get_wallet
from .models import WalletTransaction


@company_required(manage=True)
def wallet(request):
    """The balance, what every service costs, and the ledger with the breakdown of each charge."""
    from . import quote as quotes
    from django.db.models import Q, Sum
    from django.utils import timezone
    wallet_row = get_wallet(request.company)
    entries = WalletTransaction.objects.filter(company=request.company)
    kind = request.GET.get('type', '')
    groups = {'in': Q(delta__gt=0), 'out': Q(action=WalletTransaction.AI_SERVICE), 'refund': Q(action=WalletTransaction.REFUND)}
    if kind in groups:
        entries = entries.filter(groups[kind])
    else:
        kind = ''
    page = Paginator(entries, 30).get_page(request.GET.get('page'))
    month = timezone.now().replace(day=1, hour=0, minute=0, second=0, microsecond=0)
    this_month = WalletTransaction.objects.filter(company=request.company, created_at__gte=month)
    added = this_month.filter(delta__gt=0).exclude(action=WalletTransaction.REFUND).aggregate(s=Sum('delta'))['s'] or 0
    used = (this_month.filter(action=WalletTransaction.AI_SERVICE).aggregate(s=Sum('delta'))['s'] or 0) + \
           (this_month.filter(action=WalletTransaction.REFUND).aggregate(s=Sum('delta'))['s'] or 0)
    services = []
    for key in catalog.service_keys():
        svc = catalog.service(key)
        quote = quotes.make(key, 1 if catalog.unit_name(key) else None)
        services.append({'key': key, 'free': catalog.is_free(key), 'name': catalog.service_name(key, request.LANGUAGE_CODE),
                         'price': quote.amount,
                         'per_unit': quotes.unit_label(key), 'nine': (quotes.make(key, 9).amount if catalog.unit_name(key) else quotes.make(key, '9', 9).amount if catalog.page_pricing(key) else '')})
    return render(request, 'credits/wallet.html', {
        'wallet': wallet_row, 'balance': catalog.money(wallet_row.balance), 'page': page, 'services': services,
        'low': not wallet_row.is_exempt and wallet_row.balance < catalog.LOW_BALANCE, 'kind': kind,
        'month': {'added': catalog.money(added), 'used': catalog.money(-used), 'uses': this_month.filter(action=WalletTransaction.AI_SERVICE).count()},
        'packages': [{'amount': catalog.format_package(p), 'points': int(p * catalog.POINTS_PER_RIYAL)} for p in catalog.topup_packages()],
        'payments_open': payments_open(request.company), 'paid': request.GET.get('paid') == '1'})
