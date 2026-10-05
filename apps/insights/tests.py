import datetime
from unittest import mock

from django.core import mail
from django.test import TestCase
from django.urls import reverse
from django.utils import timezone

from apps.ai.client import AIResult
from apps.content.models import Post
from apps.content.tests import make_company, make_user
from apps.jobs.models import Job
from apps.jobs.runner import claim_next, run_job
from apps.social import meta
from apps.social.meta import MetaError
from apps.social.models import SocialAccount

from . import services, tasks
from .models import MonthlyReport, PostInsight


def published_post(company, hour=19, days_ago=3, title='منشور', pillar='تعليم', template='bold', external=None, **kwargs):
    when = (timezone.now() - datetime.timedelta(days=days_ago)).astimezone(company.tzinfo).replace(hour=hour, minute=0, second=0, microsecond=0)
    return Post.objects.create(company=company, title=title, headline=title, pillar=pillar, template=template, platforms=['facebook'],
                               status=Post.Status.PUBLISHED, published_at=when, scheduled_at=when,
                               external_ids=external if external is not None else {'facebook': 'p_1'}, **kwargs)


def insight(post, platform='facebook', **kwargs):
    defaults = dict(reach=100, likes=10, comments=2, shares=1, saves=0)
    defaults.update(kwargs)
    return PostInsight.objects.create(post=post, platform=platform, **defaults)


class MetaStatsTests(TestCase):
    def test_facebook_stats_from_post_insights(self):
        # The shape Meta returns (October 2026): lifetime value first, daily values with end_time after.
        reply = {'data': [
            {'name': 'post_total_media_view_unique', 'values': [{'value': 480}]},
            {'name': 'post_total_media_view_unique', 'values': [{'value': 3, 'end_time': '2026-10-01T07:00:00+0000'}]},
            {'name': 'post_reactions_by_type_total', 'values': [{'value': {'like': 10, 'love': 2}}]},
            {'name': 'post_activity_by_action_type', 'values': [{'value': {'comment': 3, 'share': 2, 'like': 12}}]},
        ]}
        with mock.patch.object(meta, '_call', return_value=reply) as call:
            self.assertEqual(meta.facebook_post_stats('p_1', 't'), {'likes': 12, 'comments': 3, 'shares': 2, 'saves': 0, 'reach': 480})
        self.assertEqual(call.call_args.args[1], 'p_1/insights')  # never the post object (needs pages_read_user_content)

    def test_facebook_stats_with_no_activity(self):
        reply = {'data': [{'name': 'post_total_media_view_unique', 'values': [{'value': 1}]},
                          {'name': 'post_reactions_by_type_total', 'values': [{'value': {}}]},
                          {'name': 'post_activity_by_action_type', 'values': [{'value': {}}]}]}
        with mock.patch.object(meta, '_call', return_value=reply):
            self.assertEqual(meta.facebook_post_stats('p_1', 't'), {'likes': 0, 'comments': 0, 'shares': 0, 'saves': 0, 'reach': 1})

    def test_instagram_stats(self):
        replies = [
            {'like_count': 40, 'comments_count': 4},
            {'data': [{'name': 'reach', 'values': [{'value': 900}]}, {'name': 'shares', 'values': [{'value': 6}]},
                      {'name': 'saved', 'values': [{'value': 9}]}]},
        ]
        with mock.patch.object(meta, '_call', side_effect=replies):
            self.assertEqual(meta.instagram_media_stats('m1', 't'), {'likes': 40, 'comments': 4, 'shares': 6, 'saves': 9, 'reach': 900})

    def test_login_asks_for_insight_scopes(self):
        with self.settings(META_APP_ID='1', META_INSIGHTS_SCOPES=['read_insights']):
            self.assertIn('read_insights', meta.login_url('https://x/cb', 's'))


class CollectTests(TestCase):
    def setUp(self):
        self.company = make_company()
        SocialAccount.objects.create(company=self.company, platform='facebook', external_id='pg', name='P', access_token='tok')
        self.post = published_post(self.company)

    def test_collect_stores_numbers_and_skips_fresh_rows(self):
        stats = {'likes': 7, 'comments': 1, 'shares': 0, 'saves': 0, 'reach': 70}
        with mock.patch('apps.social.meta.facebook_post_stats', return_value=stats) as call:
            self.assertEqual(services.collect(self.company), (1, []))
            self.assertEqual(services.collect(self.company), (0, []))  # read moments ago: not asked again
        self.assertEqual(call.call_count, 1)
        row = PostInsight.objects.get()
        self.assertEqual((row.engagement, row.rate), (8, 11.43))

    def test_manual_refresh_reads_again_at_once(self):
        stats = {'likes': 1, 'comments': 0, 'shares': 0, 'saves': 0, 'reach': 9}
        with mock.patch('apps.social.meta.facebook_post_stats', return_value=stats) as call:
            services.collect(self.company)
            services.collect(self.company, force=True)
        self.assertEqual(call.call_count, 2)

    def test_an_expired_connection_stops_after_one_failure(self):
        published_post(self.company, title='ثانٍ', external={'facebook': 'p_2'})
        with mock.patch('apps.social.meta.facebook_post_stats', side_effect=MetaError('expired', expired=True)) as call:
            updated, problems = services.collect(self.company)
        self.assertEqual((updated, call.call_count, len(problems)), (0, 1, 1))

    def test_posts_published_by_hand_are_skipped(self):
        Post.objects.filter(pk=self.post.pk).update(external_ids={})
        with mock.patch('apps.social.meta.facebook_post_stats') as call:
            self.assertEqual(services.collect(self.company), (0, []))
        call.assert_not_called()


class AggregationTests(TestCase):
    def setUp(self):
        self.company = make_company()
        # Three posts at 19:00 do well, three at 09:00 do poorly.
        for i in range(3):
            insight(published_post(self.company, hour=19, days_ago=i + 1, title=f'مساء {i}', pillar='عروض', template='offer'),
                    reach=100, likes=30)
            insight(published_post(self.company, hour=9, days_ago=i + 5, title=f'صباح {i}', pillar='تعليم', template='bold'),
                    reach=100, likes=3, comments=0, shares=0)

    def test_summary_totals_and_rankings(self):
        data = services.summarize(self.company, None, None)
        self.assertEqual(data['totals']['posts'], 6)
        self.assertEqual(data['totals']['reach'], 600)
        self.assertEqual(data['top'][0]['pillar'], 'عروض')
        self.assertEqual(data['bottom'][0]['pillar'], 'تعليم')
        self.assertEqual(data['by_pillar'][0]['name'], 'عروض')
        self.assertEqual(data['by_layout'][0]['name'], 'offer')

    def test_best_slots_need_enough_posts_and_pick_the_strong_hour(self):
        self.assertEqual(services.best_slots(self.company)[0][0], 19)
        PostInsight.objects.all().delete()
        self.assertEqual(services.best_slots(self.company), [])

    def test_range_filters_by_publish_date(self):
        start = timezone.now() - datetime.timedelta(days=4)
        self.assertEqual(services.summarize(self.company, start, None)['totals']['posts'], 3)

    def test_performance_block_empty_without_data_and_present_with_it(self):
        self.assertIn('<performance>', services.performance_block(self.company))
        PostInsight.objects.all().delete()
        self.assertEqual(services.performance_block(self.company), '')

    def test_planner_prompt_carries_the_performance(self):
        from apps.ai import planner
        from apps.content.models import ContentPlan
        plan = ContentPlan.objects.create(company=self.company, month=datetime.date(2026, 3, 1), platforms=['facebook'])
        with mock.patch.object(planner, 'call_json') as call:
            planner.generate_plan(plan)
        prompt = call.call_args[0][1]
        self.assertIn('<performance>', prompt)
        self.assertIn('عروض', prompt)


class ScheduleTests(TestCase):
    def setUp(self):
        self.company = make_company()
        self.owner = make_user('o@example.com', self.company)
        SocialAccount.objects.create(company=self.company, platform='facebook', external_id='pg', name='P', access_token='tok')

    def test_refresh_job_queued_once_when_numbers_are_stale(self):
        published_post(self.company)
        self.assertEqual(tasks.run_due(), 1)
        self.assertEqual(tasks.run_due(), 0)
        self.assertEqual(Job.objects.filter(kind=Job.Kind.FETCH_INSIGHTS).count(), 1)

    def test_no_automatic_report_for_months_before_launch(self):
        before = tasks.AUTO_REPORTS_FROM.replace(day=1) - datetime.timedelta(days=1)
        post = published_post(self.company)
        Post.objects.filter(pk=post.pk).update(published_at=datetime.datetime.combine(before.replace(day=10), datetime.time(12),
                                                                                       tzinfo=self.company.tzinfo))
        insight(post)
        now = datetime.datetime.combine(tasks.AUTO_REPORTS_FROM.replace(day=5), datetime.time(12), tzinfo=self.company.tzinfo)
        tasks.run_due(now=now)
        self.assertFalse(MonthlyReport.objects.exists())

    def test_nothing_queued_without_published_posts(self):
        self.assertEqual(tasks.run_due(), 0)

    def test_previous_month_report_queued_when_there_are_numbers(self):
        month = tasks.AUTO_REPORTS_FROM
        now = datetime.datetime.combine((month + datetime.timedelta(days=32)).replace(day=2), datetime.time(9), tzinfo=self.company.tzinfo)
        post = published_post(self.company)
        Post.objects.filter(pk=post.pk).update(published_at=datetime.datetime.combine(month.replace(day=10), datetime.time(12),
                                                                                       tzinfo=self.company.tzinfo))
        insight(post)
        tasks.run_due(now=now)
        report = MonthlyReport.objects.get(company=self.company)
        self.assertEqual(report.month, month)
        job = Job.objects.get(kind=Job.Kind.GENERATE_REPORT)
        self.assertEqual((job.params['report_id'], job.params['deliver']), (report.pk, True))
        tasks.run_due(now=now)  # not queued twice
        self.assertEqual(MonthlyReport.objects.count(), 1)

    def test_generate_report_writes_and_delivers(self):
        self.company.autopilot_client_email = 'client@example.com'
        self.company.save()
        month = tasks.previous_month(timezone.localdate())
        rep = MonthlyReport.objects.create(company=self.company, month=month)
        Job.enqueue(self.company, Job.Kind.GENERATE_REPORT, self.owner, report_id=rep.pk, deliver=True)
        ai = AIResult({'summary': 'شهر جيد', 'wins': ['أ', 'ب'], 'recommendations': ['1', '2', '3', '4']}, 10, 5, 0, 'm')
        with mock.patch('apps.ai.report.call_json', return_value=ai):
            run_job(claim_next())
        rep.refresh_from_db()
        self.assertEqual(rep.status, MonthlyReport.Status.READY)
        self.assertEqual(rep.recommendations, ['1', '2', '3'])
        self.assertTrue(rep.share_token)
        self.assertEqual(len(mail.outbox), 2)  # the client, and the owner's notification email
        self.assertIn(rep.share_token, mail.outbox[0].body)


class ViewTests(TestCase):
    def setUp(self):
        self.company = make_company()
        self.user = make_user('o@example.com', self.company)
        self.client.force_login(self.user)

    def test_dashboard_without_accounts_invites_connecting(self):
        response = self.client.get(reverse('insights:dashboard'))
        self.assertContains(response, reverse('social:accounts'))

    def test_dashboard_with_data(self):
        SocialAccount.objects.create(company=self.company, platform='facebook', external_id='pg', name='P', access_token='t')
        insight(published_post(self.company, title='أفضل منشور'))
        response = self.client.get(reverse('insights:dashboard'), {'range': '90'})
        self.assertContains(response, 'أفضل منشور')

    def test_refresh_queues_a_forced_job(self):
        self.client.post(reverse('insights:refresh'))
        self.assertTrue(Job.objects.get(kind=Job.Kind.FETCH_INSIGHTS).params['force'])

    def test_report_create_and_public_link(self):
        month = tasks.previous_month(timezone.localdate())
        response = self.client.post(reverse('insights:report_create'), {'month': month.isoformat()})
        rep = MonthlyReport.objects.get()
        self.assertRedirects(response, reverse('insights:report', args=[rep.pk]))
        self.assertTrue(Job.objects.filter(kind=Job.Kind.GENERATE_REPORT, params__report_id=rep.pk).exists())
        # Public page only for finished reports, only with the token.
        public = reverse('insights_public:public_report', args=[rep.share_token])
        self.assertEqual(self.client.get(public).status_code, 404)
        rep.status, rep.summary = MonthlyReport.Status.READY, 'ملخص التقرير'
        rep.save()
        self.client.logout()
        self.assertContains(self.client.get(public), 'ملخص التقرير')
        self.assertEqual(self.client.get(reverse('insights_public:public_report', args=['nope'])).status_code, 404)

    def test_other_companies_reports_are_hidden(self):
        other = make_company('أخرى')
        rep = MonthlyReport.objects.create(company=other, month=datetime.date(2026, 1, 1))
        self.assertEqual(self.client.get(reverse('insights:report', args=[rep.pk])).status_code, 404)
