from . import catalog


def wallet(request):
    """The balance shown in the sidebar: for the company the person is working in."""
    company = getattr(request, 'company', None)
    if company is None or not request.user.is_authenticated:
        return {}
    from .models import Wallet
    row = Wallet.objects.filter(company=company).only('balance', 'is_exempt').first()
    return {'wallet_usd': catalog.format_points(row.balance if row else 0), 'wallet_exempt': bool(row and row.is_exempt)}
