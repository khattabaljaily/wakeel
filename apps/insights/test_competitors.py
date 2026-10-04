from unittest import mock

from django.test import TestCase
from django.urls import reverse

from apps.ai.client import AIResult
from apps.companies.scrape import FetchError
from apps.content.tests import make_company, make_user
from apps.jobs.models import Job
from apps.jobs.runner import claim_next, run_job

from . import competitors
from .models import Competitor, CompetitorAnalysis

ANALYSIS = {'summary': 'ملخص', 'competitors': [{'name': 'منافس', 'positioning': 'أرخص', 'themes': ['عروض'], 'strengths': 'س',
                                               'weaknesses': 'ض'}],
            'gaps': ['خدمة ما بعد البيع'], 'opportunities': ['قصص العملاء']}
SITE = {'title': 'Rival', 'description': 'We sell', 'text': 'Cheap prices every day'}


class CompetitorTests(TestCase):
    def setUp(self):
        self.company = make_company()
        self.user = make_user('o@example.com', self.company)
        self.client.force_login(self.user)

    def test_add_edit_and_delete(self):
        url = reverse('competitors:list')
        self.client.post(url, {'name': 'منافس', 'website': 'rival.example', 'sample_posts': 'خصم اليوم'})
        rival = Competitor.objects.get(company=self.company)
        rival.site_read_at = rival.created_at
        rival.save()
        self.client.post(f'{url}?edit={rival.pk}', {'name': 'منافس', 'website': 'other.example'})
        rival.refresh_from_db()
        self.assertEqual(rival.website, 'other.example')
        self.assertIsNone(rival.site_read_at)  # a new site is read again
        self.client.post(reverse('competitors:delete', args=[rival.pk]))
        self.assertFalse(Competitor.objects.exists())

    def test_viewer_cannot_add(self):
        from apps.companies.models import Membership
        viewer = make_user('v@example.com', self.company, Membership.Role.VIEWER)
        self.client.force_login(viewer)
        self.assertEqual(self.client.post(reverse('competitors:list'), {'name': 'x'}).status_code, 403)

    def test_analysis_reads_sites_and_feeds_the_planner(self):
        Competitor.objects.create(company=self.company, name='منافس', website='rival.example', sample_posts='خصم 50% اليوم')
        Competitor.objects.create(company=self.company, name='بلا موقع', website='down.example')
        self.client.post(reverse('competitors:analyse'))
        analysis = CompetitorAnalysis.objects.get()
        self.assertEqual(Job.objects.get(kind=Job.Kind.ANALYZE_COMPETITORS).params['analysis_id'], analysis.pk)

        def read(url):
            if 'down' in url:
                raise FetchError('تعذّر الوصول')
            return SITE
        with mock.patch('apps.companies.scrape.read_site', side_effect=read), \
                mock.patch('apps.ai.competitors.call_json', return_value=AIResult(ANALYSIS, 1, 1, 0, 'm')) as call:
            job = run_job(claim_next())
        self.assertEqual(job.status, Job.Status.DONE, job.error)
        prompt = call.call_args[0][1]
        self.assertIn('Cheap prices every day', prompt)
        self.assertIn('خصم 50% اليوم', prompt)
        self.assertEqual(Competitor.objects.get(name='بلا موقع').site_error, 'تعذّر الوصول')
        analysis.refresh_from_db()
        self.assertEqual((analysis.status, analysis.gaps), (CompetitorAnalysis.Status.READY, ['خدمة ما بعد البيع']))
        block = competitors.planner_block(self.company)
        self.assertIn('قصص العملاء', block)
        self.assertContains(self.client.get(reverse('competitors:list')), 'خدمة ما بعد البيع')

    def test_recent_sites_are_not_read_again(self):
        from django.utils import timezone
        Competitor.objects.create(company=self.company, name='م', website='r.example', site_text='old', site_read_at=timezone.now())
        with mock.patch('apps.companies.scrape.read_site') as read:
            competitors.read_sites(Competitor.objects.all())
        read.assert_not_called()

    def test_no_analysis_without_competitors_and_no_block_without_analysis(self):
        self.client.post(reverse('competitors:analyse'))
        self.assertFalse(CompetitorAnalysis.objects.exists())
        self.assertEqual(competitors.planner_block(self.company), '')
