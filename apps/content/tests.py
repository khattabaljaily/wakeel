import datetime
from unittest import mock

from django.test import TestCase, override_settings
from django.urls import reverse

from apps.accounts.models import User
from apps.ai.client import AIError, AIResult
from apps.companies.models import Company, Membership
from apps.jobs.models import Job
from apps.jobs.runner import claim_next, run_job

from .models import ContentPlan, Post
from .services import apply_plan


def make_company(name='شركة', **kwargs):
    defaults = dict(industry='تقنية', country='قطر', description='وصف', timezone='Asia/Qatar')
    defaults.update(kwargs)
    return Company.objects.create(name=name, **defaults)


def make_user(email, company=None, role=Membership.Role.OWNER):
    user = User.objects.create_user(username=email, email=email, password='Pass12345!x', first_name='مستخدم')
    if company:
        Membership.objects.create(company=company, user=user, role=role)
    return user


PLAN_DATA = {
    'title': 'خطة', 'summary': 'ملخص', 'goals': ['هدف'],
    'pillars': [{'name': 'تعليم', 'description': 'د', 'share_percent': 100}],
    'key_dates': [],
    'posts': [
        {'day': 5, 'time': '19:30', 'platforms': ['facebook', 'instagram'], 'format': 'image', 'pillar': 'تعليم',
         'objective': 'وعي', 'title': 'أول', 'headline': 'عنوان', 'subheadline': 'فرعي', 'cta': 'اطلب', 'badge': '',
         'template': 'gradient', 'caption': 'نص', 'hashtags': '#وسم', 'visual_notes': '', 'video_script': ''},
        # Out-of-range day, bad time, unknown template, a platform outside the plan, TikTok forced to video.
        {'day': 45, 'time': 'late', 'platforms': ['tiktok', 'linkedin'], 'format': 'image', 'pillar': 'تعليم',
         'objective': '', 'title': '', 'headline': 'فيديو', 'subheadline': '', 'cta': '', 'badge': '',
         'template': 'neon', 'caption': 'نص', 'hashtags': '', 'visual_notes': '', 'video_script': 'مشهد'},
    ],
}


class ApplyPlanTests(TestCase):
    def setUp(self):
        self.company = make_company()
        self.plan = ContentPlan.objects.create(company=self.company, month=datetime.date(2026, 2, 1),
                                               platforms=['facebook', 'instagram', 'tiktok'])

    def test_creates_posts_in_company_timezone(self):
        posts = apply_plan(self.plan, PLAN_DATA)
        self.plan.refresh_from_db()
        self.assertEqual(self.plan.status, ContentPlan.Status.READY)
        self.assertEqual(len(posts), 2)
        first = Post.objects.get(title='أول')
        local = first.scheduled_at.astimezone(self.company.tzinfo)
        self.assertEqual((local.day, local.hour, local.minute), (5, 19, 30))
        self.assertEqual(first.status, Post.Status.REVIEW)
        self.assertEqual(first.template, 'gradient')
        self.assertEqual(first.size, Post.Size.PORTRAIT)

    def test_sanitises_bad_values(self):
        apply_plan(self.plan, PLAN_DATA)
        video = Post.objects.get(headline='فيديو')
        self.assertEqual(video.scheduled_at.astimezone(self.company.tzinfo).day, 28)  # clamped to Feb 28
        self.assertEqual(video.platforms, ['tiktok'])
        self.assertEqual(video.format, Post.Format.REEL)
        self.assertEqual(video.size, Post.Size.STORY)
        self.assertEqual(video.template, 'bold')
        self.assertEqual(video.title, 'فيديو')

    def test_regenerating_replaces_posts(self):
        apply_plan(self.plan, PLAN_DATA)
        apply_plan(self.plan, PLAN_DATA)
        self.assertEqual(self.plan.posts.count(), 2)


class GeneratePlanJobTests(TestCase):
    def setUp(self):
        self.company = make_company()
        self.user = make_user('owner@x.test', self.company)
        self.plan = ContentPlan.objects.create(company=self.company, month=datetime.date(2026, 3, 1),
                                               platforms=['facebook'], created_by=self.user)
        Job.enqueue(self.company, Job.Kind.GENERATE_PLAN, self.user, plan_id=self.plan.pk)

    @mock.patch('apps.ai.planner.call_json')
    def test_success_saves_plan_and_queues_rendering(self, call_json):
        call_json.return_value = AIResult(data=PLAN_DATA, input_tokens=1000, output_tokens=2000)
        job = run_job(claim_next())
        self.assertEqual(job.status, Job.Status.DONE, job.error)
        self.assertEqual((job.input_tokens, job.output_tokens), (1000, 2000))
        self.plan.refresh_from_db()
        self.assertEqual(self.plan.status, ContentPlan.Status.READY)
        self.assertTrue(Job.objects.filter(kind=Job.Kind.RENDER_PLAN, status=Job.Status.PENDING).exists())

    @override_settings(AI_ENABLED=False)
    def test_without_key_fails_with_readable_message(self):
        job = run_job(claim_next())
        self.assertEqual(job.status, Job.Status.FAILED)
        self.assertIn('secrets.json', job.error)
        self.plan.refresh_from_db()
        self.assertEqual(self.plan.status, ContentPlan.Status.FAILED)

    @mock.patch('apps.ai.planner.call_json', side_effect=AIError('خطأ من الخدمة'))
    def test_ai_error_marks_plan_failed(self, _):
        job = run_job(claim_next())
        self.assertEqual(job.error, 'خطأ من الخدمة')
        self.plan.refresh_from_db()
        self.assertEqual(self.plan.error, 'خطأ من الخدمة')


class TenantIsolationTests(TestCase):
    def setUp(self):
        self.a = make_company('أ')
        self.b = make_company('ب')
        self.user = make_user('a@x.test', self.a)
        self.other_post = Post.objects.create(company=self.b, title='سري', platforms=['facebook'])
        self.client.force_login(self.user)

    def test_pages_and_api_hide_other_companies(self):
        self.assertEqual(self.client.get(reverse('content:post_edit', args=[self.other_post.pk])).status_code, 404)
        self.assertEqual(self.client.get(reverse('studio:preview', args=[self.other_post.pk])).status_code, 404)
        self.assertEqual(self.client.get(reverse('api:post_detail', args=[self.other_post.pk])).status_code, 404)
        r = self.client.post(reverse('api:post_status', args=[self.other_post.pk]), {'status': 'approved'}, content_type='application/json')
        self.assertEqual(r.status_code, 404)

    def test_cannot_switch_into_foreign_company(self):
        self.assertEqual(self.client.post(reverse('companies:switch', args=[self.b.pk])).status_code, 404)


class PostWorkflowTests(TestCase):
    def setUp(self):
        self.company = make_company()
        self.owner = make_user('owner@x.test', self.company)
        self.editor = make_user('editor@x.test', self.company, Membership.Role.EDITOR)
        self.viewer = make_user('viewer@x.test', self.company, Membership.Role.VIEWER)
        self.post = Post.objects.create(company=self.company, title='منشور', platforms=['facebook'], headline='قديم',
                                        scheduled_at=datetime.datetime(2026, 4, 2, 18, 45, tzinfo=self.company.tzinfo))

    def status(self, user, value):
        self.client.force_login(user)
        return self.client.post(reverse('api:post_status', args=[self.post.pk]), {'status': value}, content_type='application/json')

    def test_only_managers_approve(self):
        self.assertEqual(self.status(self.editor, 'review').status_code, 200)
        self.assertEqual(self.status(self.editor, 'approved').status_code, 403)
        self.assertEqual(self.status(self.viewer, 'review').status_code, 403)
        self.assertEqual(self.status(self.owner, 'approved').status_code, 200)
        self.assertEqual(self.status(self.owner, 'published').status_code, 200)
        self.post.refresh_from_db()
        self.assertIsNotNone(self.post.published_at)

    def test_reschedule_keeps_time_of_day(self):
        self.client.force_login(self.editor)
        r = self.client.post(reverse('api:post_reschedule', args=[self.post.pk]), {'date': '2026-04-20'}, content_type='application/json')
        self.assertEqual(r.status_code, 200)
        self.post.refresh_from_db()
        local = self.post.scheduled_at.astimezone(self.company.tzinfo)
        self.assertEqual((local.day, local.hour, local.minute), (20, 18, 45))

    def test_editor_save_queues_render_when_design_changes(self):
        self.client.force_login(self.editor)
        data = {'title': 'منشور', 'platforms': ['facebook'], 'format': 'image', 'scheduled_at': '2026-04-02T18:45',
                'headline': 'جديد', 'template': 'bold', 'size': 'square', 'caption': 'نص'}
        r = self.client.post(reverse('content:post_edit', args=[self.post.pk]), data)
        self.assertEqual(r.status_code, 200, r.content)
        self.assertIsNotNone(r.json()['render_job'])
        self.post.refresh_from_db()
        self.assertEqual(self.post.headline, 'جديد')
        self.assertTrue(self.post.image_stale)

    def test_viewer_cannot_save(self):
        self.client.force_login(self.viewer)
        r = self.client.post(reverse('content:post_edit', args=[self.post.pk]), {'title': 'x'})
        self.assertEqual(r.status_code, 403)

    def test_pages_render(self):
        self.client.force_login(self.owner)
        for name, args in [('core:dashboard', []), ('content:calendar', []), ('content:post_list', []),
                           ('content:plan_list', []), ('content:plan_create', []), ('content:post_edit', [self.post.pk]),
                           ('companies:brand', []), ('companies:team', []), ('companies:media', [])]:
            self.assertEqual(self.client.get(reverse(name, args=args)).status_code, 200, name)
        self.assertEqual(self.client.get(reverse('content:post_list') + '?platform=facebook&q=منشور').status_code, 200)


class CancelJobTests(TestCase):
    def setUp(self):
        self.company = make_company()
        self.user = make_user('c@x.test', self.company)
        self.plan = ContentPlan.objects.create(company=self.company, month=datetime.date(2026, 3, 1), platforms=['facebook'])
        self.job = Job.enqueue(self.company, Job.Kind.GENERATE_PLAN, self.user, plan_id=self.plan.pk)
        self.client.force_login(self.user)

    def test_cancel_pending_job_fails_plan_and_worker_skips_it(self):
        r = self.client.post(reverse('api:job_cancel', args=[self.job.pk]))
        self.assertEqual(r.json()['status'], Job.Status.CANCELLED)
        self.plan.refresh_from_db()
        self.assertEqual(self.plan.status, ContentPlan.Status.FAILED)
        self.assertIsNone(claim_next())

    @mock.patch('apps.ai.planner.call_json')
    def test_result_discarded_when_cancelled_mid_run(self, call_json):
        job = claim_next()

        def cancel_then_answer(*args, **kwargs):
            self.client.post(reverse('api:job_cancel', args=[job.pk]))
            return AIResult(data=PLAN_DATA)
        call_json.side_effect = cancel_then_answer
        job = run_job(job)
        self.assertEqual(job.status, Job.Status.CANCELLED)
        self.assertEqual(self.plan.posts.count(), 0)
        self.plan.refresh_from_db()
        self.assertEqual(self.plan.status, ContentPlan.Status.FAILED)
