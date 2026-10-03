import datetime
from unittest import mock

from django.core import mail
from django.test import TestCase
from django.urls import reverse

from apps.ai.client import AIResult
from apps.jobs.models import Job
from apps.jobs.runner import claim_next, run_job

from . import autopilot
from .models import ContentPlan
from .tests import PLAN_DATA, make_company, make_user


def at(company, day, month=10, hour=9):
    return datetime.datetime(2026, month, day, hour, tzinfo=company.tzinfo)


class AutopilotTests(TestCase):
    def setUp(self):
        self.company = make_company(autopilot=True, autopilot_day=25, autopilot_platforms=['instagram'],
                                    autopilot_posts_per_week=3, autopilot_client_email='client@x.test')
        self.owner = make_user('o@x.test', self.company)

    def test_starts_next_months_plan_on_its_day_once(self):
        self.assertEqual(autopilot.run_due(at(self.company, 24)), 0)       # not yet
        self.assertEqual(autopilot.run_due(at(self.company, 25)), 1)
        plan = ContentPlan.objects.get(company=self.company)
        self.assertEqual((plan.month, plan.platforms, plan.posts_per_week, plan.autopilot),
                         (datetime.date(2026, 11, 1), ['instagram'], 3, True))
        self.assertEqual(plan.created_by, self.owner)
        job = Job.objects.get(kind=Job.Kind.GENERATE_PLAN)
        self.assertTrue(job.params['autopilot'])
        self.assertEqual(autopilot.run_due(at(self.company, 28)), 0)       # already has next month's plan

    def test_skips_companies_that_are_off_or_not_usable(self):
        self.company.autopilot = False
        self.company.save()
        self.assertEqual(autopilot.run_due(at(self.company, 26)), 0)
        self.company.autopilot, self.company.is_active = True, False
        self.company.save()
        self.assertEqual(autopilot.run_due(at(self.company, 26)), 0)

    @mock.patch('apps.studio.render.render_posts')
    @mock.patch('apps.ai.planner.call_json')
    def test_after_the_designs_the_client_gets_the_review_link(self, plan_call, _render):
        plan_call.return_value = AIResult(data=PLAN_DATA)
        autopilot.run_due(at(self.company, 25))
        run_job(claim_next())   # generate
        mail.outbox.clear()
        job = run_job(claim_next())   # render, then deliver
        self.assertEqual((job.kind, job.status), (Job.Kind.RENDER_PLAN, Job.Status.DONE))
        plan = ContentPlan.objects.get(company=self.company)
        self.assertTrue(plan.share_token)
        client_mail = [m for m in mail.outbox if m.to == ['client@x.test']]
        self.assertEqual(len(client_mail), 1)
        self.assertIn(plan.share_token, client_mail[0].body)

    def test_settings_page(self):
        self.client.force_login(self.owner)
        self.assertContains(self.client.get(reverse('companies:autopilot')), 'المخطط الآلي')
        r = self.client.post(reverse('companies:autopilot'), {
            'autopilot': 'on', 'autopilot_day': '20', 'autopilot_posts_per_week': '5',
            'autopilot_platforms': ['facebook', 'instagram'], 'autopilot_client_email': 'c@x.test'})
        self.assertRedirects(r, reverse('companies:autopilot'))
        self.company.refresh_from_db()
        self.assertEqual((self.company.autopilot_day, self.company.autopilot_posts_per_week, self.company.autopilot_platforms),
                         (20, 5, ['facebook', 'instagram']))
        bad = self.client.post(reverse('companies:autopilot'), {'autopilot': 'on', 'autopilot_day': '31',
                                                                'autopilot_posts_per_week': '4', 'autopilot_platforms': ['facebook']})
        self.assertEqual(bad.status_code, 200)  # day 31 is refused (months differ in length)
