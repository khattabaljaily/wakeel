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
    wallet_row = get_wallet(request.company)
    page = Paginator(WalletTransaction.objects.filter(company=request.company), 30).get_page(request.GET.get('page'))
    services = []
    for key in catalog.service_keys():
        svc = catalog.service(key)
        quote = quotes.make(key, 1 if catalog.unit_name(key) else None)
        services.append({'key': key, 'free': catalog.is_free(key), 'name': catalog.service_name(key, request.LANGUAGE_CODE),
                         'price': quote.usd,
                         'per_unit': quotes.unit_label(key), 'nine': (quotes.make(key, 9).usd if catalog.unit_name(key) else quotes.make(key, '9', 9).usd if catalog.page_pricing(key) else '')})
    return render(request, 'credits/wallet.html', {
        'wallet': wallet_row, 'balance': catalog.format_points(wallet_row.balance), 'page': page, 'services': services,
        'packages': [{'usd': catalog.format_package(p), 'points': int(p * 1000)} for p in catalog.topup_packages_usd()],
        'payments_open': payments_open(request.company), 'paid': request.GET.get('paid') == '1'})
