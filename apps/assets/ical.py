"""The renewal calendar as an iCalendar (.ics) feed: one all-day event per asset with a renewal date, with a reminder a week before.
Written by hand (RFC 5545): text is escaped, lines are folded at 75 bytes, line ends are CRLF."""
import datetime

from django.utils import timezone, translation
from django.utils.translation import gettext as _

from .models import Asset


def _escape(text):
    return str(text).replace('\\', '\\\\').replace(';', '\\;').replace(',', '\\,').replace('\r\n', '\\n').replace('\n', '\\n')


def _fold(line):
    """Lines longer than 75 bytes continue on the next line after one space (never cutting a multi-byte character)."""
    raw, out = line.encode('utf-8'), []
    while len(raw) > 75:
        cut = 75
        while cut > 0 and (raw[cut] & 0xC0) == 0x80:
            cut -= 1
        out.append(raw[:cut].decode('utf-8'))
        raw = b' ' + raw[cut:]
    out.append(raw.decode('utf-8'))
    return '\r\n'.join(out)


def build(company, host='wakeelservice.com'):
    """The calendar of the company's assets that have a renewal date, in the language of the company's content."""
    stamp = timezone.now().strftime('%Y%m%dT%H%M%SZ')
    with translation.override('en' if company.content_language == 'en' else 'ar'):
        lines = ['BEGIN:VCALENDAR', 'VERSION:2.0', 'PRODID:-//Wakeel//Digital assets//EN', 'CALSCALE:GREGORIAN',
                 'X-WR-CALNAME:' + _escape(_('Renewals of %(company)s') % {'company': company.name})]
        for asset in Asset.objects.for_company(company).filter(expiry_date__isnull=False).order_by('expiry_date', 'id'):
            details = [asset.get_kind_display()] + [x for x in (asset.provider, asset.identifier) if x]
            lines += ['BEGIN:VEVENT', f'UID:asset-{asset.pk}@{host}', f'DTSTAMP:{stamp}',
                      f'DTSTART;VALUE=DATE:{asset.expiry_date:%Y%m%d}',
                      f'DTEND;VALUE=DATE:{asset.expiry_date + datetime.timedelta(days=1):%Y%m%d}',
                      'SUMMARY:' + _escape(_('Renewal: %(name)s') % {'name': asset.name}),
                      'DESCRIPTION:' + _escape(' · '.join(details)),
                      'TRANSP:TRANSPARENT', 'BEGIN:VALARM', 'ACTION:DISPLAY', 'TRIGGER:-P7D',
                      'DESCRIPTION:' + _escape(_('Renewal: %(name)s') % {'name': asset.name}), 'END:VALARM', 'END:VEVENT']
        lines.append('END:VCALENDAR')
    return '\r\n'.join(_fold(line) for line in lines) + '\r\n'
