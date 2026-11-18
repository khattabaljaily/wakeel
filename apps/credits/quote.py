"""A quote: the itemised price of one paid action, made BEFORE anything is charged.

The screen shows `quote.total` on the button itself, with its lines; the form carries `quote.token` (signed), and the
charge compares it with the price worked out again: a difference (the price list changed, the units changed) refuses the
action without charging, and the person is shown the new price. This is how "the price shown is the price charged" is
kept (owner's rule, 2026-11-18, after MyDocHub showed $0.08 and charged $0.36)."""
from dataclasses import dataclass

from django.core import signing
from django.utils.translation import gettext_lazy as _

from . import catalog

SALT = 'credits.quote'
MAX_AGE = 60 * 60


@dataclass(frozen=True)
class Line:
    key: str            # 'base', 'units', or a service key for a bundled action
    points: int
    count: int | None = None


@dataclass(frozen=True)
class Quote:
    service_key: str
    units: int | None
    lines: tuple
    total: int

    @property
    def token(self) -> str:
        return signing.dumps({'s': self.service_key, 'u': self.units, 't': self.total}, salt=SALT)

    @property
    def usd(self) -> str:
        return catalog.format_points(self.total)

    @property
    def is_free(self) -> bool:
        return self.total == 0

    def described(self):
        """[(sentence, usd)] for the screen: what the price is made of."""
        out = []
        for line in self.lines:
            if line.key == 'units':
                text = _('%(count)s × %(unit)s') % {'count': line.count, 'unit': _unit_label(self.service_key)}
            else:
                text = catalog.service_name(line.key if line.key != 'base' else self.service_key, 'ar')
            out.append((text, catalog.format_points(line.points)))
        return out


def _unit_label(service_key):
    return {'post': _('post')}.get(catalog.unit_name(service_key), catalog.unit_name(service_key))


def make(service_key: str, units: int | None = None) -> Quote:
    total = catalog.price_points(service_key, units)
    if catalog.unit_name(service_key) and total:
        count = min(max(int(units or 1), 1), catalog.max_units(service_key))
        base = catalog.base_points(service_key, units)
        lines = (Line('base', base), Line('units', total - base, count))
    else:
        lines = (Line('base', total),) if total else ()
    return Quote(service_key, units if catalog.unit_name(service_key) else None, lines, total)


def bundle(*quotes: Quote) -> Quote:
    """One action that is several paid parts (the whole price is shown, each part is itemised)."""
    lines = tuple(Line(q.service_key, q.total) for q in quotes if q.total)
    return Quote('+'.join(q.service_key for q in quotes), None, lines, sum(q.total for q in quotes))


def read_token(token: str) -> dict | None:
    try:
        return signing.loads(token, salt=SALT, max_age=MAX_AGE)
    except signing.BadSignature:
        return None
