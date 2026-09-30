"""Usage and cost figures for the system admin panel, built from Job rows."""
import datetime

from django.db.models import Q
from django.utils import timezone

from apps.content.forms import ARABIC_MONTHS
from apps.jobs.models import Job


def ai_jobs(**filters):
    """Jobs that called the AI (and so used tokens), newest first."""
    return (Job.objects.filter(Q(input_tokens__gt=0) | Q(output_tokens__gt=0), **filters)
            .select_related('company', 'created_by').order_by('-created_at'))


def year_start():
    first = timezone.localtime().replace(day=1, hour=0, minute=0, second=0, microsecond=0)
    return (first - datetime.timedelta(days=335)).replace(day=1)


def month_start():
    return timezone.localtime().replace(day=1, hour=0, minute=0, second=0, microsecond=0)


def blank(label=''):
    return {'label': label, 'jobs': 0, 'input': 0, 'cache_hit': 0, 'output': 0, 'cost': 0.0, 'unpriced': 0,
            'cache_rate': 0}


def add(row, job):
    row['jobs'] += 1
    row['input'] += job.input_tokens
    row['cache_hit'] += job.cache_hit_tokens
    row['output'] += job.output_tokens
    if job.cost_usd is None:
        row['unpriced'] += 1
    else:
        row['cost'] += float(job.cost_usd)
    row['cache_rate'] = round(row['cache_hit'] * 100 / row['input']) if row['input'] else 0
    return row


def summarize(jobs):
    """(total, months newest first) for an iterable of jobs. Grouped in Python: MySQL can't truncate
    dates by timezone without its tz tables."""
    total, months = blank(), {}
    for job in jobs:
        local = timezone.localtime(job.created_at)
        label = f'{ARABIC_MONTHS[local.month - 1]} {local.year}'
        add(months.setdefault((local.year, local.month), blank(label)), job)
        add(total, job)
    return total, [row for _, row in sorted(months.items(), reverse=True)]
