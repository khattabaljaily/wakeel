import datetime
from unittest import mock

from django.test import TestCase
from django.urls import reverse
from django.utils import timezone

from apps.ai.client import AIResult
from apps.insights.models import PostInsight
from apps.jobs.models import Job
from apps.jobs.runner import claim_next, run_job

from . import copies
from .models import ContentPlan, Post
from .tests import make_company, make_user

AI_TEXT = {'title': 'Fresh', 'headline': 'New headline', 'subheadline': 'Sub', 'cta': 'Go', 'badge': '', 'caption': 'English caption',
           'hashtags': '#new', 'visual_notes': '', 'video_script': 'should be dropped'}


def ai(data=AI_TEXT):
    return AIResult(dict(data), 10, 5, 0, 'm')


def old_post(company, days=90, **kwargs):
    when = timezone.now() - datetime.timedelta(days=days)
    defaults = dict(title='قديم', headline='عنوان', platforms=['facebook'], status=Post.Status.PUBLISHED, published_at=when,
                    scheduled_at=when, template='stat', scheme='dark', motif='grid')
    defaults.update(kwargs)
    return Post.objects.create(company=company, **defaults)


@mock.patch('apps.studio.render.render_posts')
class CopyJobTests(TestCase):
    def setUp(self):
        self.company = make_company()
        self.user = make_user('o@example.com', self.company)
        self.post = old_post(self.company, caption='نص عربي')

    def test_language_version_is_a_new_post_linked_to_the_original(self, render):
        Job.enqueue(self.company, Job.Kind.VARIANT_POST, self.user, post_id=self.post.pk, language='en')
        with mock.patch('apps.ai.planner.call_json', return_value=ai()) as call:
            job = run_job(claim_next())
        self.assertEqual(job.status, Job.Status.DONE, job.error)
        self.assertIn('English', call.call_args[0][1])
        copy = Post.objects.get(source_post=self.post)
        self.assertEqual((copy.language, copy.caption, copy.video_script, copy.status), ('en', 'English caption', '', Post.Status.REVIEW))
        self.assertEqual((copy.template, copy.scheme, copy.scheduled_at), ('stat', 'dark', self.post.scheduled_at))
        self.assertEqual(Post.objects.get(pk=self.post.pk).caption, 'نص عربي')  # the original is untouched
        render.assert_called_once()
        self.client.force_login(self.user)
        detail = self.client.get(reverse('api:job_detail', args=[job.pk])).json()
        self.assertEqual(detail['result_url'], reverse('content:post_edit', args=[copy.pk]))

    def test_repost_gets_fresh_words_new_look_and_a_free_future_day(self, render):
        Job.enqueue(self.company, Job.Kind.REPOST, self.user, post_id=self.post.pk)
        with mock.patch('apps.ai.planner.call_json', return_value=ai()):
            job = run_job(claim_next())
        self.assertEqual(job.status, Job.Status.DONE, job.error)
        copy = Post.objects.get(source_post=self.post)
        self.assertEqual(copy.language, '')
        self.assertEqual(copy.headline, 'New headline')
        self.assertGreater(copy.scheduled_at, timezone.now())
        self.assertNotEqual((copy.scheme, copy.motif, copy.variant), (self.post.scheme, self.post.motif, self.post.variant))

    def test_api_refuses_unknown_language_and_other_companies(self, render):
        self.client.force_login(self.user)
        url = reverse('api:post_variant', args=[self.post.pk])
        self.assertEqual(self.client.post(url, {'language': 'klingon'}, content_type='application/json').status_code, 400)
        self.assertEqual(self.client.post(url, {'language': 'ar_sd'}, content_type='application/json').status_code, 202)
        other = old_post(make_company('أخرى'))
        self.assertEqual(self.client.post(reverse('api:post_repost', args=[other.pk])).status_code, 404)


class CandidateTests(TestCase):
    def setUp(self):
        self.company = make_company()

    def test_marked_evergreen_first_then_best_performers_and_recent_ones_left_out(self):
        good = old_post(self.company, title='جيد')
        PostInsight.objects.create(post=good, platform='facebook', likes=50)
        weak = old_post(self.company, title='ضعيف')
        PostInsight.objects.create(post=weak, platform='facebook', likes=2)
        marked = old_post(self.company, title='دائم', evergreen=True)
        old_post(self.company, title='بلا أرقام')  # no numbers, not marked: not a candidate
        fresh = old_post(self.company, days=10, title='حديث', evergreen=True)  # too recent
        self.assertEqual([p.title for p, _e in copies.candidates(self.company)], ['دائم', 'جيد', 'ضعيف'])
        # Once reposted, a post waits before it can come back.
        Post.objects.create(company=self.company, title='نسخة', source_post=good, platforms=['facebook'])
        self.assertNotIn(good, [p for p, _e in copies.candidates(self.company)])
        self.assertTrue(fresh)

    def test_free_slot_avoids_taken_days(self):
        tz = self.company.tzinfo
        start = datetime.datetime(2030, 5, 1, tzinfo=tz)
        end = datetime.datetime(2030, 5, 4, tzinfo=tz)
        for day in (2, 3):
            Post.objects.create(company=self.company, title='x', platforms=['facebook'],
                                scheduled_at=datetime.datetime(2030, 5, day, 19, tzinfo=tz))
        slot = copies.free_slot(self.company, start, end)
        self.assertIsNone(slot)  # the 1st is "today" relative to start, so only the 2nd and 3rd were open, both taken
        Post.objects.filter(scheduled_at=datetime.datetime(2030, 5, 3, 19, tzinfo=tz)).delete()
        self.assertEqual(copies.free_slot(self.company, start, end).astimezone(tz).date(), datetime.date(2030, 5, 3))

    def test_plan_generation_queues_the_monthly_reposts(self):
        self.company.evergreen_per_month = 2
        self.company.save()
        for i in range(3):
            PostInsight.objects.create(post=old_post(self.company, title=f'م{i}'), platform='facebook', likes=10 + i)
        plan = ContentPlan.objects.create(company=self.company, month=datetime.date(2030, 6, 1), platforms=['facebook'])
        self.assertEqual(copies.schedule_evergreen(plan), 2)
        self.assertEqual(Job.objects.filter(kind=Job.Kind.REPOST, params__plan_id=plan.pk).count(), 2)
        self.company.evergreen_per_month = 0
        self.assertEqual(copies.schedule_evergreen(plan), 0)

    def test_editor_save_keeps_and_clears_evergreen(self):
        user = make_user('e@example.com', self.company)
        post = old_post(self.company)
        self.client.force_login(user)
        data = {'title': 'م', 'platforms': ['facebook'], 'format': 'image', 'headline': 'ع', 'template': 'bold', 'size': 'square'}
        self.client.post(reverse('content:post_edit', args=[post.pk]), {**data, 'evergreen': 'on'})
        self.assertTrue(Post.objects.get(pk=post.pk).evergreen)
        self.assertContains(self.client.get(reverse('content:post_edit', args=[post.pk])), 'id="variantBtn"')
