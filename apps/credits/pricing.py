"""The owner's pricing rule (2026-11-03): after every cost the net profit is `profit` x the total cost.

    total cost = cost x (1 + failures) + price x (card_fees + tax)
    net profit = price - total cost = profit x total cost
    => price   = (1 + profit) x cost x (1 + failures) / (1 - (1 + profit) x (card_fees + tax))

Rounded up to the price step. With no fees: $1 -> $1.50. Same formula as enjaz-docai's `sale_price_usd`, which MyDocHub's
document services use (it comes with them in the documents phase of the merge)."""
from decimal import ROUND_CEILING, Decimal


def _d(value):
    return value if isinstance(value, Decimal) else Decimal(str(value))


def sale_price_usd(cost, *, profit=Decimal('0.5'), failures=0, card_fees=0, tax=0, step='0.01') -> Decimal:
    cost, profit, failures, card_fees, tax, step = map(_d, (cost, profit, failures, card_fees, tax, step))
    gross = Decimal(1) + profit
    room = Decimal(1) - gross * (card_fees + tax)
    if cost < 0 or profit < 0 or failures < 0 or card_fees < 0 or tax < 0 or room <= 0:
        raise ValueError('Fees and taxes leave no room for the profit, or a figure is negative.')
    exact = gross * cost * (Decimal(1) + failures) / room
    return (exact / step).to_integral_value(rounding=ROUND_CEILING) * step
