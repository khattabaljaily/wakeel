"""Charge and refund, and the one rule around them: what was shown is what is charged.

    quote = quote.make('generate_plan', units=9)           # shown on the button before anything happens
    txn = charge(company, user, quote, expected_total=shown_total)   # raises PriceChanged / InsufficientCredits
    ...the work...
    refund(txn)                                            # on failure or cancellation (once: a second call does nothing)

Fail-safe: a charge is a ledger line with its itemised breakdown; the balance is changed by one conditional UPDATE, so it can
never go below zero and two runs at once cannot spend the same points."""
from django.db import transaction
from django.db.models import F

from .models import Wallet, WalletTransaction


class InsufficientCredits(Exception):
    """The charge was refused: not enough balance."""

    def __init__(self, cost: int, balance: int, code: str = 'insufficient_credits'):
        super().__init__(f'{code}: needs {cost} points, balance {balance}')
        self.cost, self.balance, self.code = cost, balance, code


class PriceChanged(Exception):
    """The price worked out now is not the one the person was shown: nothing was charged."""

    def __init__(self, shown: int, now: int):
        super().__init__(f'price shown {shown} points, price now {now}')
        self.shown, self.now = shown, now


def get_wallet(company) -> Wallet:
    wallet, _created = Wallet.objects.get_or_create(company=company)
    return wallet


def _is_free(company, user) -> bool:
    return bool(user is not None and user.is_superuser) or get_wallet(company).is_exempt


def can_afford(company, user, quote) -> bool:
    return quote.total == 0 or _is_free(company, user) or get_wallet(company).balance >= quote.total


def ensure_can_afford(company, user, quote, expected_total=None):
    """Refuse early (before any work or record is made) when the price changed or the balance is short."""
    if expected_total is not None and int(expected_total) != quote.total:
        raise PriceChanged(int(expected_total), quote.total)
    if not can_afford(company, user, quote):
        raise InsufficientCredits(quote.total, get_wallet(company).balance)


def add_points(company, amount: int, *, action: str, user=None, description: str = '', reference: str = ''):
    """Credit (or debit, if negative) the wallet atomically and write the ledger line."""
    get_wallet(company)
    with transaction.atomic():
        Wallet.objects.filter(company=company).update(balance=F('balance') + amount)
        return WalletTransaction.objects.create(company=company, user=user, delta=amount, action=action,
                                                description=description, reference=reference)


def charge(company, user, quote, *, reference: str = '', expected_total=None):
    """Take the quote's price from the wallet. Returns the ledger line, or None when nothing is charged (a free service, an
    exempt company, a superuser)."""
    if expected_total is not None and int(expected_total) != quote.total:
        raise PriceChanged(int(expected_total), quote.total)
    if quote.total == 0 or _is_free(company, user):
        return None
    wallet = get_wallet(company)
    with transaction.atomic():
        # Conditional UPDATE: atomic, and the balance can never go below zero.
        if not Wallet.objects.filter(pk=wallet.pk, balance__gte=quote.total).update(balance=F('balance') - quote.total):
            wallet.refresh_from_db(fields=['balance'])
            raise InsufficientCredits(quote.total, wallet.balance)
        return WalletTransaction.objects.create(
            company=company, user=user, delta=-quote.total, action=WalletTransaction.AI_SERVICE,
            service_key=quote.service_key[:40], units=quote.units, reference=reference[:60],
            breakdown=[{'key': line.key, 'points': line.points, 'count': line.count} for line in quote.lines],
            description=f'AI service: {quote.service_key}')


def refund(txn, reason: str = 'failed'):
    """Give a charge back, once. Returns the refund line, or None when there was nothing to give back."""
    if txn is None or txn.delta >= 0:
        return None
    with transaction.atomic():
        original = WalletTransaction.objects.select_for_update().get(pk=txn.pk)
        if WalletTransaction.objects.filter(refund_of=original).exists():
            return None
        Wallet.objects.filter(company_id=original.company_id).update(balance=F('balance') - original.delta)
        return WalletTransaction.objects.create(
            company_id=original.company_id, user_id=original.user_id, delta=-original.delta, action=WalletTransaction.REFUND,
            service_key=original.service_key, units=original.units, reference=original.reference, refund_of=original,
            description=f'Refund: {original.service_key} {reason}')
