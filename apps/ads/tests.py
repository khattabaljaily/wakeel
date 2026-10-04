import json
from decimal import Decimal
from unittest import mock

from django.test import TestCase, override_settings
from django.urls import reverse
from django.utils import timezone

from apps.ai.client import AIResult
from apps.companies.models import Membership
from apps.content.models import Post
from apps.content.tests import make_company, make_user
from apps.jobs.runner import claim_next, run_job
from apps.social.models import SocialAccount

from . import services
from .models import AdDraft

SUGGESTION = {'daily_budget': 9999, 'days': 90, 'age_min': 10, 'age_max': 40, 'gender': 'female', 'rationale': 'منشور ناجح',
              'audience_notes': 'مهتمون بالعقارات'}


@override_settings(META_ADS_SCOPES=['ads_management'], META_GRAPH_VERSION='v23.0')
class AdsTests(TestCase):
    def setUp(self):
        self.company = make_company(country='قطر', ad_account_id='act_42', ad_account_currency='QAR')
        self.owner = make_user('o@example.com', self.company)
        SocialAccount.objects.create(company=self.company, platform='facebook', external_id='PAGE', name='P', access_token='page',
                                     user_token='user')
        self.post = Post.objects.create(company=self.company, title='منشور ناجح', platforms=['facebook'], status=Post.Status.PUBLISHED,
                                        published_at=timezone.now(), external_ids={'facebook': 'PAGE_9'})
        self.client.force_login(self.owner)

    def suggest(self):
        self.client.post(reverse('ads:suggest', args=[self.post.pk]))
        with mock.patch('apps.ai.ads.call_json', return_value=AIResult(SUGGESTION, 1, 1, 0, 'm')):
            run_job(claim_next())
        return AdDraft.objects.get()

    def test_suggestion_is_clamped_to_safe_limits(self):
        draft = self.suggest()
        self.assertEqual(draft.status, AdDraft.Status.SUGGESTED)
        self.assertEqual((draft.daily_budget, draft.days), (Decimal('500.00'), 30))
        self.assertEqual((draft.age_min, draft.age_max, draft.gender, draft.countries), (18, 40, 'female', 'QA'))

    def test_create_makes_everything_paused(self):
        draft = self.suggest()
        draft.daily_budget = Decimal('12.50')
        draft.save()
        calls = []

        def fake(method, path, **kwargs):
            calls.append((method, path, kwargs.get('data') or kwargs.get('params')))
            return {'id': f'id{len(calls)}'}
        with mock.patch('apps.ads.services._call', side_effect=fake):
            self.client.post(reverse('ads:create', args=[draft.pk]))
        draft.refresh_from_db()
        self.assertEqual(draft.status, AdDraft.Status.CREATED, draft.error)
        paths = [c[1] for c in calls]
        self.assertEqual(paths, ['act_42/campaigns', 'act_42/adsets', 'act_42/adcreatives', 'act_42/ads'])
        statuses = [c[2].get('status') for c in calls if 'status' in c[2]]
        self.assertEqual(statuses, ['PAUSED', 'PAUSED', 'PAUSED'])
        adset = calls[1][2]
        self.assertEqual(adset['daily_budget'], 1250)  # minor units
        self.assertEqual(json.loads(adset['targeting'])['genders'], [2])
        self.assertEqual(calls[2][2]['object_story_id'], 'PAGE_9')
        self.assertTrue(all(c[2]['access_token'] == 'user' for c in calls))

    def test_editors_cannot_create_and_bad_budgets_are_refused(self):
        draft = self.suggest()
        editor = make_user('e@example.com', self.company, Membership.Role.EDITOR)
        self.client.force_login(editor)
        with mock.patch('apps.ads.services._call') as call:
            self.assertEqual(self.client.post(reverse('ads:create', args=[draft.pk])).status_code, 403)
        call.assert_not_called()
        r = self.client.post(reverse('ads:draft', args=[draft.pk]), {'daily_budget': '0', 'days': 5, 'age_min': 18, 'age_max': 30,
                                                                    'gender': 'all', 'countries': 'QA'})
        self.assertContains(r, 'invalid-feedback')

    def test_disabled_without_ads_permission(self):
        with self.settings(META_ADS_SCOPES=[]):
            self.assertFalse(services.enabled(self.company))
            self.assertContains(self.client.get(reverse('ads:list')), 'alert-info')

    def test_other_companies_drafts_are_hidden(self):
        other = make_company('أخرى')
        post = Post.objects.create(company=other, title='x', platforms=['facebook'])
        draft = AdDraft.objects.create(company=other, post=post)
        self.assertEqual(self.client.get(reverse('ads:draft', args=[draft.pk])).status_code, 404)
        self.assertEqual(self.client.post(reverse('ads:suggest', args=[post.pk])).status_code, 404)
