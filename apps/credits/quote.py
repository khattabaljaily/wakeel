"""A quote: the itemised price of one paid action, made BEFORE anything is charged.

The screen shows `quote.total` on the button itself, with its lines; the form carries `quote.token` (signed), and the
charge compares it with the price worked out again: a difference (the price list changed, the units changed) refuses the
action without charging, and the person is shown the new price. This is how "the price shown is the price charged" is
kept (owner's rule, 2026-11-18, after MyDocHub showed $0.08 and charged $0.36)."""
from dataclasses import dataclass

from django.core import signing
from django.utils.translation import get_language
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
    units: object        # an int (posts), or the dense pages as a string (a document service)
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
                text = catalog.service_name(line.key if line.key != 'base' else self.service_key, (get_language() or 'en').split('-')[0])
            out.append((text, catalog.format_points(line.points)))
        return out


def unit_label(service_key):
    """The name of a service's unit for people, in the reader's language: 'post' -> 'منشور'."""
    if service_key.startswith('presentation'):
        return _('slide')                         # a deck is priced by the slide (a source document's pages are counted as slides)
    if catalog.page_pricing(service_key):
        return _('page')
    return {'post': _('post')}.get(catalog.unit_name(service_key), catalog.unit_name(service_key))


_unit_label = unit_label


def make(service_key: str, units=None, pages: int | None = None) -> Quote:
    """The quote of one run. For a service priced by the page (`units` = the dense pages the document is worth, `pages` the pages
    read) the lines are the fixed price and the pages."""
    if catalog.page_pricing(service_key):
        total = catalog.price_points(service_key, units, pages)
        dense = catalog.dense_pages(service_key, pages, units)
        base = catalog.base_points(service_key, units, pages)
        lines = tuple(line for line in (Line('base', base), Line('units', total - base, dense)) if line.points)
        return Quote(service_key, str(dense), lines, total)
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
