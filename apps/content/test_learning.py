import datetime
from unittest import mock

from django.test import TestCase
from django.urls import reverse

from apps.ai.client import AIResult
from apps.jobs.models import Job
from apps.jobs.runner import claim_next, run_job

from .models import ContentPlan, LearningSignal, Post
from .tests import PLAN_DATA, make_company, make_user


class LearningTests(TestCase):
    def setUp(self):
        self.company = make_company()
        self.owner = make_user('o@x.test', self.company)
        self.plan = ContentPlan.objects.create(company=self.company, month=datetime.date(2026, 10, 1),
                                               platforms=['facebook'], status=ContentPlan.Status.READY)
        self.post = Post.objects.create(company=self.company, plan=self.plan, title='فكرة', platforms=['facebook'],
                                        headline='عنوان طويل جداً كتبه الذكاء الاصطناعي', caption='نص رسمي جداً',
                                        scheduled_at=datetime.datetime(2026, 10, 3, 19, tzinfo=self.company.tzinfo))
        self.client.force_login(self.owner)

    def save(self, **changes):
        data = {'title': self.post.title, 'platforms': ['facebook'], 'format': 'image', 'scheduled_at': '2026-10-03T19:00',
                'headline': self.post.headline, 'template': 'bold', 'size': 'square', 'caption': self.post.caption}
        data.update(changes)
        self.assertEqual(self.client.post(reverse('content:post_edit', args=[self.post.pk]), data).status_code, 200)
        Job.objects.filter(kind=Job.Kind.RENDER_POST).delete()  # saving queues a redesign; not what these tests run
        self.post.refresh_from_db()

    def test_edits_become_one_signal_per_field(self):
        self.save(headline='عنوان قصير')
        self.save(headline='عنوان أقصر')          # updates the same pending signal
        signal = LearningSignal.objects.get(field='headline')
        self.assertEqual((signal.before, signal.after), ('عنوان طويل جداً كتبه الذكاء الاصطناعي', 'عنوان أقصر'))
        self.save(headline='عنوان طويل جداً كتبه الذكاء الاصطناعي')  # edited back: nothing to learn
        self.assertFalse(LearningSignal.objects.filter(field='headline').exists())

    def test_change_requests_rewrites_and_client_feedback_are_recorded(self):
        self.client.post(reverse('api:post_status', args=[self.post.pk]), {'status': 'draft', 'note': 'بلاش لغة رسمية'},
                         content_type='application/json')
        self.client.post(reverse('api:post_rewrite', args=[self.post.pk]), {'instruction': 'اجعله أقصر'}, content_type='application/json')
        kinds = sorted(LearningSignal.objects.values_list('kind', flat=True))
        self.assertEqual(kinds, ['changes', 'rewrite'])

    @mock.patch('apps.ai.learning.call_json')
    def test_distill_keeps_manual_lessons_and_marks_signals_used(self, call_json):
        self.company.lessons = [{'text': 'لا تذكر الأسعار', 'manual': True}, {'text': 'قديمة', 'manual': False}]
        self.company.save()
        self.save(caption='نص ودود وقصير')
        call_json.return_value = AIResult(data={'lessons': ['اكتب بأسلوب ودود', 'اجعل النص قصيراً']})
        Job.enqueue(self.company, Job.Kind.LEARN, self.owner)
        job = run_job(claim_next())
        self.assertEqual(job.status, Job.Status.DONE, job.error)
        self.company.refresh_from_db()
        self.assertEqual([l['text'] for l in self.company.lessons], ['لا تذكر الأسعار', 'اكتب بأسلوب ودود', 'اجعل النص قصيراً'])
        self.assertFalse(LearningSignal.objects.filter(used=False).exists())
        prompt = call_json.call_args.args[1]
        self.assertIn('نص رسمي جداً', prompt)
        self.assertIn('قديمة', prompt)          # learned lessons are revised...
        self.assertNotIn('لا تذكر الأسعار', prompt)  # ...manual ones are never touched

    @mock.patch('apps.ai.learning.call_json')
    @mock.patch('apps.ai.planner.call_json')
    def test_plan_learns_first_and_prompt_carries_lessons_and_recent_posts(self, plan_call, learn_call):
        self.save(caption='نص ودود')
        learn_call.return_value = AIResult(data={'lessons': ['اكتب بأسلوب ودود']})
        plan_call.return_value = AIResult(data=PLAN_DATA)
        nov = ContentPlan.objects.create(company=self.company, month=datetime.date(2026, 11, 1), platforms=['facebook'])
        Job.enqueue(self.company, Job.Kind.GENERATE_PLAN, self.owner, plan_id=nov.pk)
        job = run_job(claim_next())
        self.assertEqual(job.status, Job.Status.DONE, job.error)
        prompt = plan_call.call_args.args[1]
        self.assertIn('<learned_preferences>', prompt)
        self.assertIn('اكتب بأسلوب ودود', prompt)
        self.assertIn('فكرة', prompt)  # October's post is listed so November doesn't repeat it

    def test_team_manages_lessons_on_the_brand_page(self):
        url = reverse('companies:lessons')
        self.client.post(url, {'action': 'add', 'text': 'لا تستخدم الإيموجي'})
        self.company.refresh_from_db()
        self.assertEqual(self.company.lessons, [{'text': 'لا تستخدم الإيموجي', 'manual': True}])
        self.assertContains(self.client.get(reverse('companies:brand')), 'لا تستخدم الإيموجي')
        self.client.post(url, {'action': 'delete', 'index': '0'})
        self.company.refresh_from_db()
        self.assertEqual(self.company.lessons, [])
