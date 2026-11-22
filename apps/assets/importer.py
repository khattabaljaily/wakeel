"""Adding many assets at once from a CSV file (the file a spreadsheet saves with "Save as CSV"). The first row names the columns; a
row that is wrong is skipped and reported, the others are saved. At most MAX_ROWS rows and MAX_BYTES bytes."""
import csv
import datetime
import io

from django.utils.translation import gettext as _

from .forms import AssetForm
from .models import Asset

MAX_ROWS = 500
MAX_BYTES = 1024 * 1024
COLUMNS = ['name', 'type', 'provider', 'address', 'account', 'start_date', 'renewal_date', 'auto_renew', 'cost', 'currency', 'billing',
           'responsible', 'notes']
YES = {'1', 'yes', 'y', 'true', 'x', 'نعم', 'ايوه', 'أيوه'}
SAMPLE = ['alofoq-trading.com', 'domain', 'GoDaddy', 'alofoq-trading.com', 'info@alofoq-trading.com', '2025-03-14', '2027-03-14', 'yes',
          '45', 'USD', 'yearly', '', '']


class ImportFailed(Exception):
    """The file cannot be read at all (too big, not text, no rows)."""


def template_csv():
    """The empty file to fill in: the columns and one example row. UTF-8 with a mark so Excel shows Arabic correctly."""
    out = io.StringIO()
    writer = csv.writer(out)
    writer.writerow(COLUMNS)
    writer.writerow(SAMPLE)
    return '\ufeff' + out.getvalue()


def _lookup(value, choices):
    """A choice's key from what was written: the key itself, or its name in the current language (any case)."""
    wanted = (value or '').strip().lower()
    for key, label in choices:
        if wanted in (key.lower(), str(label).lower()):
            return key
    return None


def _clean(value):
    return (value or '').strip()


def read(upload, company):
    """Save the valid rows of the file. Returns (how many saved, [(row number, why)]). Raises ImportFailed for a file that cannot be read."""
    raw = upload.read(MAX_BYTES + 1)
    if len(raw) > MAX_BYTES:
        raise ImportFailed(_('The file must be smaller than 1 MB.'))
    try:
        text = raw.decode('utf-8-sig')
    except UnicodeDecodeError:
        raise ImportFailed(_('The file must be a CSV saved as UTF-8.'))
    sample = text[:2048]
    try:
        dialect = csv.Sniffer().sniff(sample, delimiters=',;\t')
    except csv.Error:
        dialect = csv.excel
    reader = csv.DictReader(io.StringIO(text), dialect=dialect)
    if not reader.fieldnames or 'name' not in [(f or '').strip().lower() for f in reader.fieldnames]:
        raise ImportFailed(_('The first row must name the columns, starting with "name". Download the template to see them.'))
    members = {m.user.email.lower(): m.user.pk for m in company.memberships.select_related('user')}
    saved, problems = 0, []
    for number, row in enumerate(reader, start=2):
        if number - 1 > MAX_ROWS:
            problems.append((number, _('Only the first %(n)s rows are read.') % {'n': MAX_ROWS}))
            break
        row = {(k or '').strip().lower(): _clean(v) for k, v in row.items() if k}
        if not any(row.values()):
            continue
        kind = _lookup(row.get('type') or Asset.DOMAIN, Asset.KINDS)
        cycle = _lookup(row.get('billing') or Asset.YEARLY, Asset.CYCLES)
        if kind is None:
            problems.append((number, _('Unknown type: %(v)s') % {'v': row.get('type', '')}))
            continue
        if cycle is None:
            problems.append((number, _('Unknown billing: %(v)s') % {'v': row.get('billing', '')}))
            continue
        email = row.get('responsible', '').lower()
        if email and email not in members:
            problems.append((number, _('%(v)s is not a member of the company.') % {'v': email}))
            continue
        data = {'name': row.get('name'), 'kind': kind, 'provider': row.get('provider', ''), 'identifier': row.get('address', ''),
                'account': row.get('account', ''), 'start_date': row.get('start_date', ''), 'expiry_date': row.get('renewal_date', ''),
                'cost': row.get('cost', '').replace(',', '.'), 'currency': row.get('currency') or 'USD', 'cycle': cycle,
                'responsible': members.get(email, ''), 'notes': row.get('notes', '')}
        if row.get('auto_renew', '').lower() in YES:
            data['auto_renew'] = 'on'
        form = AssetForm(data, company=company)
        if not form.is_valid():
            first = next(iter(form.errors.values()))[0]
            problems.append((number, f'{first}'))
            continue
        asset = form.save(commit=False)
        asset.company = company
        asset.save()
        saved += 1
    return saved, problems
