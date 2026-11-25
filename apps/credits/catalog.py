"""The price list (pricing_v1.json) and the maths around it. The riyal (Qatar) is the base currency: one point = 0.001 riyal, so
a 5 riyal service costs 5,000 points. Prices are whole riyals, never below 1. Costs stay in dollars (what the AI providers
charge) and are converted at the central bank's fixed rate. Nothing here touches the database."""
import json
import math
from decimal import Decimal
from functools import lru_cache
from pathlib import Path

from django.utils.translation import get_language

from .pricing import sale_price_usd

PRICING_FILE = Path(__file__).with_name('pricing_v1.json')
POINTS_PER_RIYAL = 1000
QAR = 'QAR'
LOW_BALANCE = 4000                      # points: under 4 riyals (about a dollar) the wallet is called low
QAR_PER_USD = Decimal('3.64')          # the Qatar Central Bank's fixed rate (apps.money.currencies.PEGS)


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


def _raw_riyals(cost_usd) -> Decimal:
    """What a cost in dollars sells for, in riyals and not yet rounded: cost + profit by the owner's rule, converted at the
    central bank's fixed rate."""
    return sale_price_usd(cost_usd, step='0.000001', **_rules()) * QAR_PER_USD


def whole(riyals) -> int:
    """Points for a price in riyals, rounded UP to a whole riyal and never below 1 (owner's rule, 2026-11-25: no fractions of a riyal).
    Rounding happens once, on the whole price of a run, so a run of many units is not overcharged by rounding each part."""
    return max(1, math.ceil(Decimal(str(riyals)))) * POINTS_PER_RIYAL


def page_pricing(key: str) -> dict | None:
    """{'max_pages', 'fixed_cost_usd'} for a service priced by the page (the document services), else None. Its
    `measured_cost_usd` is the cost of one dense page (see enjaz_docai.pricing), so the price of a page is worked out
    from it; the fixed price is paid once per run on top."""
    return service(key).get('per_page')


def _fixed_riyals(key: str) -> Decimal:
    """The part of a page-priced run's price that does not grow with the pages (unrounded)."""
    spec = page_pricing(key)
    fixed = Decimal(str(spec.get('fixed_cost_usd', 0))) if spec else Decimal(0)
    return _raw_riyals(fixed) if fixed else Decimal(0)


def _page_riyals(key: str) -> Decimal:
    """The price of one dense page of a page-priced service (unrounded)."""
    svc = service(key)
    if svc.get('price') is not None:              # a price the owner set, in riyals: it is the price of a design
        return Decimal(str(svc['price']))
    return _raw_riyals(Decimal(str(svc['measured_cost_usd'])))


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
    """What a company pays for one run, from the price file, in whole riyals (as points). The price is worked out on the whole
    cost and rounded up once. 0 for a free service. A price set by the owner (`price_overrides`) is the price itself."""
    if is_free(key):
        return 0
    if page_pricing(key):       # a document service: the fixed price plus the price of a dense page for each dense page it is worth
        return whole(_fixed_riyals(key) + _page_riyals(key) * dense_pages(key, pages, units))
    if (owner := service(key).get('price')) is not None:      # a price the owner set for one run (creating a form)
        return whole(owner)
    return whole(_raw_riyals(cost_usd(key, units)))


def base_points(key: str, units=None, pages: int | None = None) -> int:
    """The share of the price that does not grow with the units (for the itemised quote), never more than the price."""
    if page_pricing(key):
        fixed = _fixed_riyals(key)
    else:
        cost = Decimal(str(service(key).get('fixed_cost_usd', 0)))
        fixed = _raw_riyals(cost) if cost else Decimal(0)
    return min(whole(fixed) if fixed else 0, price_points(key, units, pages))


def topup_packages() -> list[Decimal]:
    """The top-up packages on sale (whole riyals, smallest first); points credited = riyals x 1000, no bonus."""
    return sorted(Decimal(str(v)) for v in load()['rules']['topup_packages_qar'])


def format_package(amount) -> str:
    """A package's amount for display and for the form value: Decimal('20') -> '20'."""
    text = f'{Decimal(str(amount)):f}'
    return text.rstrip('0').rstrip('.') if '.' in text else text


def topup_points(amount) -> int:
    """Points credited for a package. ValueError when the amount is not one of the packages."""
    amount = Decimal(str(amount))
    if amount not in topup_packages():
        raise ValueError('Choose one of the top-up packages: ' + ', '.join(format_package(p) for p in topup_packages()))
    return int(amount * POINTS_PER_RIYAL)


def format_points(points) -> str:
    """An amount of riyals as a number: 5000 -> '5', 1250000 -> '1,250'. (A balance carried over from the dollar days may hold
    a fraction: 440 -> '0.44'.)"""
    value = Decimal(int(points or 0)) / POINTS_PER_RIYAL
    return f'{value:,.0f}' if value == value.to_integral_value() else f'{value:,.2f}'


def _language(language: str = '') -> str:
    return (language or get_language() or 'en').lower()


def unit(language: str = '') -> str:
    """The riyal's sign in the reader's language: 'ر.ق' in Arabic, 'QAR' in English."""
    from apps.money import currencies
    return currencies.symbol(QAR, _language(language)).strip('\u200f\u200e\u00a0 .')


# An Arabic amount reads number first, then the sign, from the right: the sign lands on the LEFT of the number (owner's decision,
# 2026-11-25, after a first version put it on the right by mistake). The number comes first in an isolated right-to-left run, so
# it is the same whatever the surrounding text's direction (a dir="ltr" badge, an Arabic sentence, an e-mail): the run is closed
# by U+2069 and cannot be reordered by what is around it.
RLI, PDI = '\u2067', '\u2069'


def money_pattern(language: str = '') -> str:
    """The amount's shape with {n} where the number goes: '{n} QAR', or in Arabic '{n} ر.ق' read right to left (the sign shows left
    of the number)."""
    if _language(language).startswith('ar'):
        return f'{RLI}{{n}} {unit(language)}{PDI}'
    return f'{{n}} {unit(language)}'


def money_html(points, language: str = '') -> str:
    """The same amount for a big number on a screen: the sign is wrapped in <small class="wk-unit"> so it can be set smaller than the
    figure. The caller marks it safe (the pieces are escaped here)."""
    from django.utils.html import escape
    sign = unit(language)
    return money_pattern(language).replace(sign, f'<small class="wk-unit">{escape(sign)}</small>').replace('{n}', escape(format_points(points)))


def money(points, language: str = '') -> str:
    """An amount as people read it: '20 QAR', and in Arabic the sign right of the number."""
    return money_pattern(language).replace('{n}', format_points(points))
