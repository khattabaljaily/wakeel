"""The console's tables (see apps.core.tables): columns, sorting and search, declared once."""
from django.db.models import Q
from django.urls import reverse

from apps.companies.models import Membership
from apps.core.tables import Col, Table


def _search_subscriptions(queryset, text):
    by_member = Membership.objects.filter(user__email__icontains=text).values('company_id')
    return queryset.filter(Q(name__icontains=text) | Q(industry__icontains=text) | Q(country__icontains=text)
                           | Q(city__icontains=text) | Q(email__icontains=text) | Q(pk__in=by_member))


def subscriptions():
    return Table(
        'subsTable', 'ops/rows/subscription.html', [
            Col('name', 'المشترك', order='name'),
            Col('industry', 'المجال', order='industry'),
            Col('end', 'الاشتراك', order='subscription_expires'),
            Col('members', 'الفريق', order='members', cls='text-center'),
            Col('status', 'الحالة'),
            Col('actions', '', cls='text-end'),
        ],
        url=reverse('ops:subscriptions_data'), search=_search_subscriptions,
        empty='لا توجد اشتراكات', row_class=lambda c: 'is-pending' if not c.is_approved else '',
    )


def _search_jobs(queryset, text):
    return queryset.filter(Q(company__name__icontains=text) | Q(model__icontains=text) | Q(error__icontains=text)
                           | Q(error_detail__icontains=text) | Q(created_by__email__icontains=text))


def jobs(company=None):
    """All jobs, or one company's (its page leaves the company column out)."""
    columns = [
        Col('id', '#', order='pk'),
        Col('company', 'الشركة', order='company__name'),
        Col('kind', 'المهمة', order='kind'),
        Col('status', 'الحالة', order='status'),
        Col('created', 'التاريخ', order='created_at'),
        Col('model', 'النموذج', order='model'),
        Col('tokens', 'الرموز (مُدخلة · cache · مُخرجة)', order='input_tokens', cls='text-end'),
        Col('cost', 'التكلفة', order='cost_usd', cls='text-end'),
    ]
    url = reverse('ops:jobs_data')
    if company is not None:
        columns = [c for c in columns if c.key != 'company']
        url += f'?company={company.pk}'
    return Table('jobsTable', 'ops/rows/job.html', columns, url=url, search=_search_jobs, order=('created', 'desc'),
                 page_length=20 if company else 25, empty='لا توجد مهام',
                 row_class=lambda j: 'is-failed' if j.status == 'failed' else '')


def usage_months(id='monthsTable'):
    return Table(id, 'ops/rows/usage_month.html', [
        Col('month', 'الشهر', order='key'),
        Col('jobs', 'المهام', order='jobs', cls='text-end'),
        Col('input', 'مُدخلة', order='input', cls='text-end'),
        Col('cache', 'cache hit', order='cache_rate', cls='text-end'),
        Col('output', 'مُخرجة', order='output', cls='text-end'),
        Col('cost', 'التكلفة', order='cost', cls='text-end'),
    ], order=('month', 'desc'), paging=False, empty='لا يوجد استهلاك بعد')


def breakdown(id, heading):
    return Table(id, 'ops/rows/breakdown.html', [
        Col('label', heading, order='label'),
        Col('jobs', 'المهام', order='jobs', cls='text-end'),
        Col('input', 'مُدخلة', order='input', cls='text-end'),
        Col('cache', 'cache hit', order='cache_rate', cls='text-end'),
        Col('cost', 'التكلفة', order='cost', cls='text-end'),
    ], order=('cost', 'desc'), paging=False, empty='لا يوجد استهلاك بعد')


def usage_companies():
    return Table('companiesUsageTable', 'ops/rows/usage_company.html', [
        Col('company', 'الشركة', order='company.name'),
        Col('jobs', 'المهام', order='year.jobs', cls='text-end'),
        Col('input', 'مُدخلة', order='year.input', cls='text-end'),
        Col('cache', 'cache hit', order='year.cache_rate', cls='text-end'),
        Col('month', 'تكلفة الشهر', order='month.cost', cls='text-end'),
        Col('year', 'تكلفة 12 شهراً', order='year.cost', cls='text-end'),
    ], order=('year', 'desc'), page_length=10, empty='لا يوجد استهلاك بعد')


def latest_subscriptions():
    return Table('latestTable', 'ops/rows/latest.html', [
        Col('name', 'المشترك', order='company.name'),
        Col('owner', 'المالك', order='owner.email'),
        Col('status', 'الحالة'),
        Col('cost', 'تكلفة الشهر', order='month.cost', cls='text-end'),
    ], paging=False, empty='لا توجد اشتراكات بعد')
