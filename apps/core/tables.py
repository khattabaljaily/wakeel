"""DataTables for every table in the app, desktop as a table and phones as cards (as in enjazpms).

A table is declared once: its columns, and one template that renders each cell and the row's
mobile card. The template gets the row as `r` and the part to render as `part` (a column key,
or "card"), so a cell and its card are written side by side and can't drift apart.

Two modes, the same markup and script (static/js/tables.js):
- client: every row is rendered into the page; DataTables sorts, searches and pages in the browser.
  For short tables (reports, the team).
- server: the page holds only the header; rows come from `Table.json()` a page at a time,
  with search, sorting and filters done in the database. For lists that grow (subscriptions, jobs).
"""
import json
from decimal import Decimal
from dataclasses import dataclass

from django.http import JsonResponse
from django.middleware.csrf import get_token
from django.template.loader import get_template
from django.utils.safestring import mark_safe
from django.utils.translation import gettext_lazy as _

MAX_PAGE = 100


@dataclass
class Col:
    key: str
    title: str = ''
    # Sorting: the ORM field in server mode; in client mode, the attribute (or dict key) whose value
    # sorts the column (dates and numbers sort by value, not by their display). None = not sortable.
    order: str | None = None
    cls: str = ''


class Table:
    def __init__(self, id, template, columns, *, url=None, search=None, order=None, page_length=25,
                 paging=True, empty=_('لا توجد بيانات'), row_class=None):
        self.id, self.template, self.columns = id, template, columns
        self.url = url                    # set = server mode
        self.search = search              # server mode: (queryset, text) -> queryset
        self.order = order                # initial sort, e.g. ('created', 'desc'); None = the queryset's own
        self.page_length, self.paging, self.empty = page_length, paging, empty
        self.row_class = row_class        # row -> extra <tr> class

    @property
    def mode(self):
        return 'server' if self.url else 'client'

    @property
    def initial_order(self):
        """DataTables' `order` option, as JSON for the data-order attribute."""
        if not self.order:
            return '[]'
        index = [c.key for c in self.columns].index(self.order[0])
        return json.dumps([[index, self.order[1]]])

    def _base(self, request, context):
        """What the row templates may use. Not a RequestContext: its context processors would run their
        queries again for every cell of every row; a table only needs the user, the company and the CSRF token."""
        return {'request': request, 'user': request.user, 'csrf_token': get_token(request),
                'company': getattr(request, 'company', None), 'membership': getattr(request, 'membership', None),
                **(context or {})}

    def _part(self, template, base, row, part):
        # strip() would return a plain str, and the page would then escape the rendered HTML.
        return mark_safe(template.render({**base, 'r': row, 'part': part}).strip())

    def rows(self, objects, request, context=None):
        """Client mode: every row, with its cells, sort values and card, for templates/_datatable.html."""
        template, base = get_template(self.template), self._base(request, context)
        return [{
            'cls': self.row_class(row) if self.row_class else '',
            'cells': [{'html': self._part(template, base, row, col.key), 'cls': col.cls,
                       'sort': _resolve(row, col.order) if col.order else None} for col in self.columns],
            'card': self._part(template, base, row, 'card'),
        } for row in objects]

    def json(self, request, queryset, context=None, prepare=None):
        """Server mode: one page of rows in DataTables' JSON format. `prepare(rows)` may decorate the
        page's objects (owners, counts) before they're rendered."""
        params = request.GET
        total = queryset.count()
        text = params.get('search[value]', '').strip()
        if text and self.search:
            queryset = self.search(queryset, text)
        filtered = queryset.count() if text else total

        keys = {params.get(f'columns[{i}][data]') for i in range(len(self.columns))}
        index = params.get('order[0][column]')
        if index is not None and index.isdigit() and int(index) < len(self.columns):
            col = self.columns[int(index)]
            if col.order and col.key in keys:
                sign = '-' if params.get('order[0][dir]') == 'desc' else ''
                queryset = queryset.order_by(f'{sign}{col.order}', '-pk')

        start = _int(params.get('start'), 0)
        length = min(_int(params.get('length'), self.page_length), MAX_PAGE)
        page = list(queryset[start:start + length])
        if prepare:
            prepare(page)
        template, base = get_template(self.template), self._base(request, context)
        data = []
        for row in page:
            item = {col.key: self._part(template, base, row, col.key) for col in self.columns}
            item['card'] = self._part(template, base, row, 'card')
            if self.row_class:
                item['DT_RowClass'] = self.row_class(row)
            data.append(item)
        return JsonResponse({'draw': _int(params.get('draw'), 0), 'recordsTotal': total,
                             'recordsFiltered': filtered, 'data': data})


def _int(value, default):
    try:
        return max(int(value), 0)
    except (TypeError, ValueError):
        return default


def _resolve(row, path):
    value = row
    for name in path.split('.'):
        value = value.get(name) if isinstance(value, dict) else getattr(value, name, None)
        if value is None:
            return ''
    if hasattr(value, 'isoformat'):
        return value.isoformat()
    if isinstance(value, (int, float, Decimal)) and not isinstance(value, bool):
        # As text: the Arabic locale would print 1.35 as "1,35", which DataTables reads as 135.
        return str(value)
    return value
