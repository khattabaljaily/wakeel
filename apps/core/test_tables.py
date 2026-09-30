import datetime

from django.db import connection
from django.test import TestCase
from django.test.utils import CaptureQueriesContext
from django.urls import reverse

from apps.accounts.models import User
from apps.companies.models import Company, Membership
from apps.jobs.models import Job


class DataTableEndpointTests(TestCase):
    """The server-side tables answer DataTables' requests: paging, sorting, search, filters, and a card per row."""

    def setUp(self):
        self.admin = User.objects.create_superuser(username='root@t.test', email='root@t.test', password='Strong-pass-123')
        self.client.force_login(self.admin)
        for i in range(30):
            c = Company.objects.create(name=f'شركة {i:02d}', industry='تجارة', country='قطر', description='و',
                                       subscription_expires=datetime.date(2027, 1, 1) + datetime.timedelta(days=i))
            owner = User.objects.create_user(username=f'o{i}@t.test', email=f'o{i}@t.test', password='x')
            Membership.objects.create(company=c, user=owner, role=Membership.Role.OWNER)
            Job.objects.create(company=c, kind=Job.Kind.GENERATE_PLAN, status=Job.Status.DONE, input_tokens=10, output_tokens=5)

    def get(self, name, **params):
        return self.client.get(reverse(f'ops:{name}'), {'draw': 1, 'start': 0, 'length': 10, **params}).json()

    def test_paging_and_totals(self):
        data = self.get('subscriptions_data', start=20)
        self.assertEqual((data['recordsTotal'], data['recordsFiltered'], len(data['data'])), (30, 30, 10))
        self.assertEqual(set(data['data'][0]), {'name', 'industry', 'end', 'members', 'status', 'actions', 'card', 'DT_RowClass'})

    def test_sorting_by_a_column(self):
        # Column 2 is "end" (subscription_expires).
        data = self.get('subscriptions_data', **{'order[0][column]': 2, 'order[0][dir]': 'asc',
                                                  **{f'columns[{i}][data]': k for i, k in enumerate(
                                                      ['name', 'industry', 'end', 'members', 'status', 'actions'])}})
        self.assertIn('شركة 00', data['data'][0]['name'])

    def test_search_reaches_owner_emails(self):
        data = self.get('subscriptions_data', **{'search[value]': 'o17@t.test'})
        self.assertEqual(data['recordsFiltered'], 1)
        self.assertIn('شركة 17', data['data'][0]['card'])

    def test_a_page_costs_a_few_queries_whatever_its_size(self):
        with CaptureQueriesContext(connection) as small:
            self.get('subscriptions_data', length=2)
        with CaptureQueriesContext(connection) as big:
            self.get('subscriptions_data', length=25)
        self.assertEqual(len(small), len(big))
        with CaptureQueriesContext(connection) as small:
            self.get('jobs_data', length=2)
        with CaptureQueriesContext(connection) as big:
            self.get('jobs_data', length=25)
        self.assertEqual(len(small), len(big))

    def test_page_size_is_capped(self):
        self.assertEqual(len(self.get('jobs_data', length=5000)['data']), 30)  # all 30, but never more than 100

    def test_pages_carry_the_table_and_its_assets(self):
        for name in ('subscriptions', 'jobs', 'usage', 'overview'):
            html = self.client.get(reverse(f'ops:{name}')).content.decode()
            self.assertIn('data-wk-table=', html, name)
            self.assertIn('js/tables.js', html, name)


class TeamTableTests(TestCase):
    def test_members_render_as_rows_and_cards(self):
        company = Company.objects.create(name='فريق', industry='ت', country='قطر', description='و')
        owner = User.objects.create_user(username='o@team.test', email='o@team.test', password='Strong-pass-123', first_name='خطاب')
        editor = User.objects.create_user(username='e@team.test', email='e@team.test', password='Strong-pass-123', first_name='سارة')
        Membership.objects.create(company=company, user=owner, role=Membership.Role.OWNER)
        Membership.objects.create(company=company, user=editor, role=Membership.Role.EDITOR)
        self.client.force_login(owner)
        response = self.client.get(reverse('companies:team'))
        rows = response.context['rows']
        self.assertEqual(len(rows), 2)
        self.assertIn('سارة', rows[1]['card'])
        self.assertIn('csrfmiddlewaretoken', rows[1]['card'])  # the card's role / remove forms work
        self.assertContains(response, 'template class="wk-dt__card"', count=2)
        self.assertContains(response, '<article class="wk-mcard">', count=2)  # rendered HTML, not escaped text
        self.assertNotContains(response, '&lt;article')


class SortValueTests(TestCase):
    def test_numbers_are_written_unlocalized(self):
        from django.template import Context, Template
        from apps.core.tables import _resolve
        value = _resolve({'year': {'cost': 1.3456}}, 'year.cost')
        self.assertEqual(Template('{{ v }}').render(Context({'v': value})), '1.3456')  # not "1,3456"
        self.assertEqual(_resolve({'n': 12000}, 'n'), '12000')
