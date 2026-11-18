"""The price list (pricing_v1.json) and the maths around it. One point = $0.001, so a $0.12 service costs 120 points.
Nothing here touches the database."""
import json
from decimal import Decimal
from functools import lru_cache
from pathlib import Path

from .pricing import sale_price_usd

PRICING_FILE = Path(__file__).with_name('pricing_v1.json')
POINTS_PER_DOLLAR = 1000


class UnknownService(KeyError):
    """The service has no entry in the price list, so it cannot be sold."""


@lru_cache(maxsize=1)
def load() -> dict:
    return json.loads(PRICING_FILE.read_text(encoding='utf-8'))


def service_keys() -> list[str]:
    return list(load()['services'])


def service(key: str) -> dict:
    try:
        return load()['services'][key]
    except KeyError:
        raise UnknownService(key) from None


def is_free(key: str) -> bool:
    """A gift of the platform: run, tracked, never charged."""
    return bool(service(key).get('free'))


def service_name(key: str, language: str = 'en') -> str:
    svc = service(key)
    return svc['name_ar'] if language == 'ar' else svc.get('name_en', key)


def _rules() -> dict:
    rules = load()['rules']['price']
    return {k: Decimal(str(rules[k])) for k in ('profit', 'failures', 'card_fees', 'tax')}


def _points(cost_usd) -> int:
    price = sale_price_usd(cost_usd, step=load()['rules']['price_step_usd'], **_rules())
    return int((price * POINTS_PER_DOLLAR).to_integral_value())


def unit_name(key: str) -> str:
    return service(key).get('unit', '')


def max_units(key: str) -> int:
    return int(service(key).get('max_units', 1))


def cost_usd(key: str, units: int | None = None) -> Decimal:
    """What one run costs us (the file's measured or estimated figures): the fixed part plus the unit cost for each unit."""
    svc = service(key)
    fixed = Decimal(str(svc.get('fixed_cost_usd', 0)))
    per_unit = Decimal(str(svc.get('unit_cost_usd', 0)))
    if not per_unit:
        return fixed
    return fixed + per_unit * min(max(int(units or 1), 1), max_units(key))


def price_points(key: str, units: int | None = None) -> int:
    """What a company pays for one run, from the price file. The price is worked out on the whole cost and rounded up once
    (rounding each part up would overcharge a plan of many posts). 0 for a free service. An admin's change to a stored
    price row is applied by `models.ServiceCost.get_points`."""
    if is_free(key):
        return 0
    return max(1, _points(cost_usd(key, units)))


def base_points(key: str, units: int | None = None) -> int:
    """The share of the price that does not grow with the units (for the itemised quote), never more than the price."""
    fixed = Decimal(str(service(key).get('fixed_cost_usd', 0)))
    return min(_points(fixed) if fixed else 0, price_points(key, units))


def topup_packages_usd() -> list[Decimal]:
    """The top-up packages on sale (USD, smallest first); points credited = dollars x 1000, no bonus. The card processor takes
    a fixed fee (~$0.30) plus ~3%, so there is no smaller package."""
    return sorted(Decimal(str(v)) for v in load()['rules']['topup_packages_usd'])


def format_package(amount) -> str:
    """A package's amount for display and for the form value: Decimal('10') -> '10', Decimal('2.5') -> '2.5'."""
    text = f'{Decimal(str(amount)):f}'
    return text.rstrip('0').rstrip('.') if '.' in text else text


def topup_points(amount_usd) -> int:
    """Points credited for a package. ValueError when the amount is not one of the packages."""
    amount = Decimal(str(amount_usd))
    if amount not in topup_packages_usd():
        raise ValueError('Choose one of the top-up packages: ' + ', '.join(f'${format_package(p)}' for p in topup_packages_usd()))
    return int(amount * POINTS_PER_DOLLAR)


def format_points(points) -> str:
    """A price for display next to a $ sign: 120 -> '0.12', 5000 -> '5.00', 1250000 -> '1,250.00'."""
    return f'{Decimal(int(points or 0)) / POINTS_PER_DOLLAR:,.2f}'
