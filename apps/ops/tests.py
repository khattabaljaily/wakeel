import datetime
from decimal import Decimal
from unittest import mock

from django.test import TestCase, override_settings
from django.urls import reverse

from apps.companies.models import Membership
from apps.content.models import ContentPlan
from apps.content.tests import make_company, make_user
from apps.jobs.models import Job
from apps.jobs.runner import claim_next, run_job


class OpsPanelTests(TestCase):
    def setUp(self):
        self.a = make_company('أ')
        self.b = make_company('ب')
        self.owner = make_user('owner@x.test', self.a)
        make_user('b@x.test', self.b)
        self.admin = make_user('root@x.test')
        self.admin.is_superuser = self.admin.is_staff = True
        self.admin.save()
        Job.objects.create(company=self.a, kind=Job.Kind.GENERATE_PLAN, status=Job.Status.DONE, input_tokens=1_000_000,
                           cache_hit_tokens=250_000, output_tokens=500_000, model='deepseek-v4-pro', cost_usd=Decimal('1.5'))
        Job.objects.create(company=self.b, kind=Job.Kind.REWRITE_POST, status=Job.Status.FAILED, input_tokens=100,
                           output_tokens=0, model='deepseek-v4-pro', cost_usd=Decimal('0.25'),
                           error='خدمة الذكاء الاصطناعي غير متاحة حالياً', error_detail='DeepSeek balance too low [HTTP 402]')

    def test_hidden_from_everyone_but_superusers(self):
        for name, args in (('overview', []), ('subscriptions', []), ('usage', []), ('jobs', []),
                           ('system', []), ('company', [self.a.pk])):
            url = reverse(f'ops:{name}', args=args)
            self.client.force_login(self.owner)
            self.assertEqual(self.client.get(url).status_code, 404, url)
            self.client.logout()
            self.assertEqual(self.client.get(url).status_code, 302, url)  # to the login page

    def test_every_console_page_renders(self):
        self.client.force_login(self.admin)
        for name, args in (('overview', []), ('subscriptions', []), ('usage', []), ('jobs', []),
                           ('system', []), ('company', [self.a.pk])):
            self.assertEqual(self.client.get(reverse(f'ops:{name}', args=args)).status_code, 200, name)

    def test_overview_figures(self):
        self.client.force_login(self.admin)
        response = self.client.get(reverse('ops:overview'))
        self.assertEqual(response.context['this_month']['cost'], 1.75)
        self.assertEqual(response.context['cost_series'][-1]['value'], 1.75)  # this month is the last column
        self.assertEqual(len(response.context['cost_series']), 12)
        self.assertEqual([r['company'].name for r in response.context['top']], ['أ', 'ب'])  # most expensive first
        self.assertEqual(response.context['counts']['failed_week'], 1)
        self.assertContains(response, 'DeepSeek balance too low')  # recent failures with their technical cause

    def test_usage_breakdowns(self):
        self.client.force_login(self.admin)
        response = self.client.get(reverse('ops:usage'))
        self.assertEqual(response.context['total']['cost'], 1.75)
        self.assertEqual(len(response.context['models_rows']), 1)
        self.assertIn('deepseek-v4-pro', response.context['models_rows'][0]['cells'][0]['html'])
        self.assertEqual(response.context['companies_rows'][0]['cells'][0]['html'].count(self.a.name), 1)

    def test_company_and_jobs_pages(self):
        self.client.force_login(self.admin)
        response = self.client.get(reverse('ops:company', args=[self.a.pk]))
        self.assertEqual(response.context['total']['cache_rate'], 25)
        data = self.client.get(reverse('ops:jobs_data'), {'status': 'failed'}).json()
        self.assertEqual(data['recordsTotal'], 1)
        self.assertIn('HTTP 402', data['data'][0]['status'])  # the cause, in the row and in its card
        self.assertIn('HTTP 402', data['data'][0]['card'])
        # A company's page lists only its jobs.
        data = self.client.get(reverse('ops:jobs_data'), {'company': self.a.pk}).json()
        self.assertEqual(data['recordsTotal'], 1)

    def test_companies_search(self):
        self.client.force_login(self.admin)
        data = self.client.get(reverse('ops:subscriptions_data'), {'search[value]': 'b@x.test', 'draw': 3}).json()
        self.assertEqual((data['draw'], data['recordsTotal'], data['recordsFiltered']), (3, 2, 1))
        self.assertIn('ب', data['data'][0]['name'])


class ConsoleSeparationTests(TestCase):
    """System admins get their own console, like the enjazpms / enjazims admin dashboards."""

    def setUp(self):
        self.company = make_company()
        self.owner = make_user('owner@x.test', self.company)
        self.admin = make_user('root@x.test', self.company)  # even a superuser who belongs to a company
        self.admin.is_superuser = self.admin.is_staff = True
        self.admin.save()

    def test_superuser_lands_on_the_console(self):
        self.client.force_login(self.admin)
        self.assertRedirects(self.client.get(reverse('core:dashboard')), reverse('ops:overview'))
        self.assertRedirects(self.client.get(reverse('core:home')), reverse('ops:overview'))
        self.assertRedirects(self.client.get(reverse('content:plan_list')), reverse('ops:overview'))

    def test_login_takes_superuser_to_the_console(self):
        response = self.client.post(reverse('accounts:login'), {'username': 'root@x.test', 'password': 'Pass12345!x'}, follow=True)
        self.assertEqual(response.redirect_chain[-1][0], reverse('ops:overview'))

    def test_each_side_has_its_own_navigation(self):
        self.client.force_login(self.admin)
        console = self.client.get(reverse('ops:overview')).content.decode()
        self.assertIn('مشرف النظام', console)
        self.assertIn(reverse('ops:subscriptions'), console)
        self.assertNotIn('/ops/users/', console)
        self.assertNotIn(reverse('content:plan_list'), console)
        self.assertNotIn('wk-bell__btn', console)

        self.client.force_login(self.owner)
        app = self.client.get(reverse('core:dashboard')).content.decode()
        self.assertIn(reverse('content:plan_list'), app)
        self.assertNotIn('/ops/', app)
        self.assertNotIn('مشرف النظام', app)


class TemplateCommentTests(TestCase):
    """Django's {# #} comments are single-line; a multi-line one is printed on the page."""

    def test_no_multiline_hash_comments(self):
        import re
        from pathlib import Path
        from django.conf import settings
        for path in (settings.BASE_DIR / 'templates').rglob('*.html'):
            for match in re.finditer(r'\{#(.*?)#\}', path.read_text(), re.S):
                self.assertNotIn('\n', match.group(1), f'{path} has a multi-line {{# #}} comment')


import datetime as _dt  # noqa: E402
import tempfile as _tempfile  # noqa: E402
from pathlib import Path as _Path  # noqa: E402
from unittest import mock as _mock  # noqa: E402

from django.test import SimpleTestCase, override_settings  # noqa: E402

from . import backup  # noqa: E402


class BackupRetentionTests(SimpleTestCase):
    def test_keeps_last_days_and_one_per_week(self):
        runs = [(_dt.datetime(2026, 8, 1) + _dt.timedelta(days=i), _Path(f'/b/{i}')) for i in range(60)]
        keep = backup._keep(runs, daily=7, weekly=4)
        self.assertTrue({_Path(f'/b/{i}') for i in range(53, 60)} <= keep)   # last 7 days
        self.assertLessEqual(len(keep), 7 + 4)
        self.assertNotIn(_Path('/b/0'), keep)

    def test_run_writes_status_and_prunes_old_dumps(self):
        with _tempfile.TemporaryDirectory() as root, _tempfile.TemporaryDirectory() as media:
            (_Path(media) / 'posts').mkdir()
            (_Path(media) / 'posts' / 'a.png').write_bytes(b'x' * 100)
            (_Path(root) / 'db').mkdir()
            for i in range(20):  # old dumps from last month
                (_Path(root) / 'db' / f'202609{i + 1:02d}-0330.sql.gz').write_bytes(b'old')

            def fake_dump(target):
                target.write_bytes(b'dump')
            with override_settings(BACKUP_DIR=root, MEDIA_ROOT=media, BACKUP_KEEP_DAILY=7, BACKUP_KEEP_WEEKLY=4,
                                   BACKUP_MAX_GB=1, BACKUP_MIN_FREE_GB=0), \
                    _mock.patch.object(backup, '_dump_database', side_effect=fake_dump):
                status = backup.run()
                again = backup.run()  # the second media snapshot hard-links unchanged files
            self.assertTrue(status['ok'], status['error'])
            self.assertLessEqual(again['db_runs'], 11)
            snaps = sorted((_Path(root) / 'media').iterdir())
            self.assertTrue((snaps[-1] / 'posts' / 'a.png').exists())
