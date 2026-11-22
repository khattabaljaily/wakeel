"""Reading a domain's real end date from its registry (RDAP). The server only ever contacts the fixed RDAP service, never
an address typed by a member; the typed name is validated as a public host name and only used in the lookup path."""
import datetime
import json
import re
import urllib.error
import urllib.request

from django.utils import timezone
from django.utils.translation import gettext as _

from .models import Asset

TIMEOUT = 8
RDAP = 'https://rdap.org/domain/'
HOST_RE = re.compile(r'^(?=.{1,253}$)([a-z0-9]([a-z0-9-]{0,61}[a-z0-9])?\.)+[a-z]{2,63}$')


class CheckError(Exception):
    """The check could not read a date; the message says why, in the member's language."""


def hostname(value):
    """'https://Example.com:443/path' -> 'example.com'. Raises CheckError for anything that is not a host name."""
    value = (value or '').strip().lower()
    value = re.sub(r'^[a-z][a-z0-9+.-]*://', '', value)
    value = re.split(r'[/?#]', value, maxsplit=1)[0].rsplit('@', 1)[-1]
    value = re.sub(r':\d+$', '', value).strip('.')
    try:
        value = value.encode('idna').decode('ascii')
    except UnicodeError:
        raise CheckError(_('This is not a valid domain name.'))
    if not HOST_RE.match(value):
        raise CheckError(_('This is not a valid domain name.'))
    return value


def domain_expiry(identifier):
    """The date the domain registration ends, from the public registry data (RDAP)."""
    host = hostname(identifier)
    request = urllib.request.Request(RDAP + host, headers={'Accept': 'application/rdap+json', 'User-Agent': 'Wakeel/1.0'})
    try:
        with urllib.request.urlopen(request, timeout=TIMEOUT) as response:
            data = json.loads(response.read(1024 * 1024))
    except urllib.error.HTTPError as error:
        if error.code == 404:
            raise CheckError(_('The registry has no record of this domain.'))
        raise CheckError(_('The registry did not answer.'))
    except (OSError, ValueError):
        raise CheckError(_('The registry did not answer.'))
    for event in data.get('events', []):
        if event.get('eventAction') == 'expiration' and event.get('eventDate'):
            try:
                return datetime.date.fromisoformat(event['eventDate'][:10])
            except ValueError:
                break
    raise CheckError(_('The registry does not publish the end date of this domain.'))


READERS = {Asset.DOMAIN: domain_expiry}


def run(asset):
    """Check one asset and store the outcome. A date that was read replaces the renewal date (and starts its reminders
    again when it changed); a failure only records why, and leaves the date the member typed. Returns True when a date was read."""
    reader = READERS.get(asset.kind)
    if reader is None or not asset.identifier:
        return False
    asset.checked_at = timezone.now()
    try:
        found = reader(asset.identifier)
    except CheckError as error:
        asset.check_status, asset.check_note = Asset.FAILED, str(error)[:200]
        found = None
    else:
        asset.check_status, asset.check_note = Asset.OK, ''
        if found != asset.expiry_date:
            asset.expiry_date, asset.reminded_days = found, None
    Asset.all_companies.filter(pk=asset.pk).update(
        checked_at=asset.checked_at, check_status=asset.check_status, check_note=asset.check_note,
        expiry_date=asset.expiry_date, reminded_days=asset.reminded_days)
    return found is not None
