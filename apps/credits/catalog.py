"""The price list (pricing_v1.json) and the maths around it. One point = $0.001, so a $0.12 service costs 120 points.
Nothing here touches the database."""
import json
import math
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
    """This app's price file with the shared price list of the document services (enjaz-docai) merged in: the same service
    costs the same in every Enjaz app, so those entries live in the library, never here."""
    from enjaz_docai import pricing
    data = json.loads(PRICING_FILE.read_text(encoding='utf-8'))
    shared = pricing.services()
    clash = set(shared) & set(data['services'])
    if clash:
        raise ValueError(f'Priced both here and in enjaz-docai: {sorted(clash)}')
    data['services'] = {**data['services'], **shared}
    for key, price in (data.get('price_overrides') or {}).items():      # services whose price is a value set by the owner, not cost + profit
        if key in data['services']:
            data['services'][key] = {**data['services'][key], 'price': price}
    return data


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


def is_launched(key: str) -> bool:
    """Built and sold in the app. A priced service without code yet has "launch": false in the price file."""
    return service(key).get('launch', True)


def service_name(key: str, language: str = 'en') -> str:
    svc = service(key)
    return svc['name_ar'] if language == 'ar' else svc.get('name_en', key)


def _rules() -> dict:
    rules = load()['rules']['price']
    return {k: Decimal(str(rules[k])) for k in ('profit', 'failures', 'card_fees', 'tax')}


def _points(cost_usd) -> int:
    price = sale_price_usd(cost_usd, step=load()['rules']['price_step_usd'], **_rules())
    return int((price * POINTS_PER_DOLLAR).to_integral_value())


def page_pricing(key: str) -> dict | None:
    """{'max_pages', 'fixed_cost_usd'} for a service priced by the page (the document services), else None. Its
    `measured_cost_usd` is the cost of one dense page (see enjaz_docai.pricing), so the price of a page is worked out
    from it; the fixed price is paid once per run on top."""
    return service(key).get('per_page')


def fixed_points(key: str) -> int:
    """The part of a page-priced run's price that does not grow with the pages."""
    spec = page_pricing(key)
    fixed = Decimal(str(spec.get('fixed_cost_usd', 0))) if spec else Decimal(0)
    return _points(fixed) if fixed else 0


def page_points(key: str) -> int:
    """The price of one dense page of a page-priced service."""
    svc = service(key)
    if svc.get('price') is not None:              # a price the owner set: it is the price of a design
        return max(1, int((Decimal(str(svc['price'])) * POINTS_PER_DOLLAR).to_integral_value()))
    return max(1, _points(Decimal(str(svc['measured_cost_usd']))))


def dense_pages(key: str, pages=None, units=None) -> Decimal:
    """What the document is worth in dense pages: `units` when it was measured (see apps.docops.density), else every page read
    counts as one (1 when unknown, at most max_pages)."""
    from enjaz_docai import pricing
    return Decimal(str(units)) if units is not None else Decimal(pricing.pages_read(page_pricing(key), pages))


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


def price_points(key: str, units=None, pages: int | None = None) -> int:
    """What a company pays for one run, from the price file. The price is worked out on the whole cost and rounded up once
    (rounding each part up would overcharge a plan of many posts). 0 for a free service. A price set by the owner
    (`price_overrides`) is the price itself."""
    if is_free(key):
        return 0
    if page_pricing(key):       # a document service: the fixed price plus the price of a dense page for each dense page it is worth
        return fixed_points(key) + max(1, math.ceil(page_points(key) * dense_pages(key, pages, units)))
    if (owner := service(key).get('price')) is not None:      # a price the owner set for one run (creating a form)
        return max(1, int((Decimal(str(owner)) * POINTS_PER_DOLLAR).to_integral_value()))
    return max(1, _points(cost_usd(key, units)))


def base_points(key: str, units=None, pages: int | None = None) -> int:
    """The share of the price that does not grow with the units (for the itemised quote), never more than the price."""
    if page_pricing(key):
        return min(fixed_points(key), price_points(key, units, pages))
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
