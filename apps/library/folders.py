"""The folders of the documents list: the papers uploaded here, by category."""
import datetime

from django.db.models import Count
from django.utils import timezone

from apps.documents.models import DocumentTemplate

from .models import SOON_DAYS, Record

# The category names are already collective ("Letters and certificates"), so a folder is named after its category.
ICONS = {Record.COMPANY: 'bi-building', Record.FINANCE: 'bi-cash-coin', Record.EMPLOYEES: 'bi-person-badge',
         Record.CONTRACTS: 'bi-pen', Record.LETTERS: 'bi-award', Record.OTHER: 'bi-folder'}


def expiring():
    """Records of the active company that expire within SOON_DAYS, or already have."""
    limit = timezone.localdate() + datetime.timedelta(days=SOON_DAYS)
    return Record.objects.filter(expiry_date__isnull=False, expiry_date__lte=limit)


def folders():
    """Counts for every folder of the active company, for the category pills."""
    kept = dict(Record.objects.values_list('category').annotate(n=Count('id')))
    for key, n in DocumentTemplate.objects.values_list('category').annotate(n=Count('id')):   # one list: the papers kept and the templates
        kept[key] = kept.get(key, 0) + n
    return {
        'count_records': sum(kept.values()),
        'count_expiring': expiring().count(),
        'categories': [(key, label, ICONS[key], kept.get(key, 0)) for key, label in Record.CATEGORIES],
    }
