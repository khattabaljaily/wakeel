"""A weekly e-mail to the owners and administrators of each company: what is late and what is due within SOON_DAYS, in one list, so
they do not depend on one reminder per asset. Run it once a week (`manage.py send_asset_digest`, from cron). A company with nothing
late or due gets nothing; a person who turned the e-mails off in their account gets nothing."""
import datetime
import logging

from django.conf import settings
from django.core.mail import send_mail
from django.urls import reverse
from django.utils import timezone, translation
from django.utils.translation import gettext as _
from django.utils.translation import ngettext

from apps.companies.models import Company
from apps.notifications.services import managers

from .models import SOON_DAYS, Asset

logger = logging.getLogger(__name__)


def collect(company):
    """(late, due) assets of the company, each soonest first."""
    soon = timezone.localdate() + datetime.timedelta(days=SOON_DAYS)
    rows = Asset.objects.for_company(company).filter(expiry_date__isnull=False, expiry_date__lte=soon).order_by('expiry_date', 'name')
    late = [a for a in rows if a.days_left < 0]
    return late, [a for a in rows if a.days_left >= 0]


def _line(asset):
    left = asset.days_left
    if left < 0:
        when = ngettext('%(n)s day late', '%(n)s days late', -left) % {'n': -left}
    elif left == 0:
        when = _('Today')
    else:
        when = ngettext('In %(n)s day', 'In %(n)s days', left) % {'n': left}
    return f'- {asset.name} ({asset.get_kind_display()}) · {asset.expiry_date:%Y-%m-%d} · {when}'


def compose(company, late, due):
    """(subject, body) in the current language."""
    subject = _('%(company)s: %(n)s digital assets to renew') % {'company': company.name, 'n': len(late) + len(due)}
    parts = [_('Digital assets of %(company)s that need attention:') % {'company': company.name}]
    for title, rows in ((_('Late'), late), (_('Due within 30 days'), due)):
        if rows:
            parts += ['', f'{title}:'] + [_line(a) for a in rows]
    parts += ['', _('Open the list:') + ' ' + settings.SITE_URL.rstrip('/') + reverse('assets:list') + '?status=soon', '',
              _('You receive this summary every week because you manage the company.')]
    return subject, '\n'.join(parts)


def send_all():
    """Send the digests. Returns the number of e-mails sent."""
    sent = 0
    for company in Company.objects.all():
        late, due = collect(company)
        if not (late or due):
            continue
        for user in managers(company):
            if not (user.is_active and user.email and user.email_notifications):
                continue
            with translation.override(user.language or settings.LANGUAGE_CODE):
                subject, body = compose(company, late, due)
            try:
                send_mail(subject, body, None, [user.email])
            except Exception:                       # one mailbox must not stop the others
                logger.exception('Could not e-mail the assets digest of company %s to user %s', company.pk, user.pk)
            else:
                sent += 1
    return sent
