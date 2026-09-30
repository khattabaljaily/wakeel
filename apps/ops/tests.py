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
        for url in (reverse('ops:overview'), reverse('ops:jobs'), reverse('ops:company', args=[self.a.pk])):
            self.client.force_login(self.owner)
            self.assertEqual(self.client.get(url).status_code, 404)
            self.client.logout()
            self.assertEqual(self.client.get(url).status_code, 302)  # to the login page

    def test_overview_totals_across_companies(self):
        self.client.force_login(self.admin)
        response = self.client.get(reverse('ops:overview'))
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.context['total']['cost'], 1.75)
        rows = response.context['company_rows']
        self.assertEqual([r['company'].name for r in rows], ['أ', 'ب'])  # most expensive first
        self.assertEqual(rows[0]['owner'], self.owner)
        self.assertContains(response, 'DeepSeek balance too low')  # recent failures with their technical cause

    def test_company_and_jobs_pages(self):
        self.client.force_login(self.admin)
        response = self.client.get(reverse('ops:company', args=[self.a.pk]))
        self.assertEqual(response.context['total']['cache_rate'], 25)
        response = self.client.get(reverse('ops:jobs'), {'status': 'failed'})
        self.assertEqual(len(response.context['page']), 1)
        self.assertContains(response, 'HTTP 402')

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
