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
        for name, args in (('overview', []), ('companies', []), ('users', []), ('usage', []), ('jobs', []),
                           ('system', []), ('company', [self.a.pk])):
            url = reverse(f'ops:{name}', args=args)
            self.client.force_login(self.owner)
            self.assertEqual(self.client.get(url).status_code, 404, url)
            self.client.logout()
            self.assertEqual(self.client.get(url).status_code, 302, url)  # to the login page

    def test_every_console_page_renders(self):
        self.client.force_login(self.admin)
        for name, args in (('overview', []), ('companies', []), ('users', []), ('usage', []), ('jobs', []),
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
        self.assertEqual([r['label'] for r in response.context['by_model']], ['deepseek-v4-pro'])
        self.assertEqual(response.context['by_company'][0]['company'], self.a)

    def test_company_and_jobs_pages(self):
        self.client.force_login(self.admin)
        response = self.client.get(reverse('ops:company', args=[self.a.pk]))
        self.assertEqual(response.context['total']['cache_rate'], 25)
        response = self.client.get(reverse('ops:jobs'), {'status': 'failed'})
        self.assertEqual(len(response.context['page']), 1)
        self.assertContains(response, 'HTTP 402')

    def test_companies_search(self):
        self.client.force_login(self.admin)
        response = self.client.get(reverse('ops:companies'), {'q': 'b@x.test'})
        self.assertEqual([r['company'] for r in response.context['page']], [self.b])

    def test_suspend_and_restore_a_user(self):
        self.client.force_login(self.admin)
        url = reverse('ops:user_toggle_active', args=[self.owner.pk])
        self.client.post(url)
        self.owner.refresh_from_db()
        self.assertFalse(self.owner.is_active)
        self.client.logout()
        self.assertFalse(self.client.login(username='owner@x.test', password='Pass12345!x'))
        self.client.force_login(self.admin)
        self.client.post(url)
        self.owner.refresh_from_db()
        self.assertTrue(self.owner.is_active)
        # Other system admins can't be suspended from here.
        self.assertEqual(self.client.post(reverse('ops:user_toggle_active', args=[self.admin.pk])).status_code, 404)

    def test_superuser_without_company_can_open_the_panel(self):
        self.assertFalse(Membership.objects.filter(user=self.admin).exists())
        self.client.force_login(self.admin)
        self.assertEqual(self.client.get(reverse('ops:overview')).status_code, 200)


class SubscriberSeesNoTechnicalDetailTests(TestCase):
    def setUp(self):
        self.company = make_company()
        self.owner = make_user('owner@x.test', self.company)
        self.client.force_login(self.owner)

    @override_settings(AI_ENABLED=False, META_ENABLED=False)
    def test_pages_hide_configuration(self):
        for name in ('core:dashboard', 'content:plan_create', 'social:accounts'):
            html = self.client.get(reverse(name)).content.decode()
            for word in ('secrets.json', 'API_KEY', 'META_APP', 'DeepSeek', 'Claude', 'manage.py', 'لوحة النظام',
                         'الذكاء الاصطناعي متصل', 'الذكاء الاصطناعي غير مفعّل'):
                self.assertNotIn(word, html, f'{name} shows {word!r}')

    def test_usage_page_is_gone(self):
        self.assertEqual(self.client.get('/company/usage/').status_code, 404)

    @mock.patch('apps.ai.planner.call_json', side_effect=RuntimeError('KeyError deep in the parser'))
    def test_unexpected_failure_keeps_traceback_for_admins_only(self, _):
        plan = ContentPlan.objects.create(company=self.company, month=datetime.date(2026, 11, 1), platforms=['facebook'])
        Job.enqueue(self.company, Job.Kind.GENERATE_PLAN, self.owner, plan_id=plan.pk)
        job = run_job(claim_next())
        plan.refresh_from_db()
        self.assertNotIn('KeyError', job.error)
        self.assertNotIn('KeyError', plan.error)
        self.assertIn('KeyError deep in the parser', job.error_detail)


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
        self.assertIn(reverse('ops:users'), console)
        self.assertNotIn(reverse('content:plan_list'), console)
        self.assertNotIn('wk-bell__btn', console)

        self.client.force_login(self.owner)
        app = self.client.get(reverse('core:dashboard')).content.decode()
        self.assertIn(reverse('content:plan_list'), app)
        self.assertNotIn('/ops/', app)
        self.assertNotIn('مشرف النظام', app)
