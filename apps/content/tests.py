import datetime
from unittest import mock

from django.test import TestCase, override_settings
from django.urls import reverse
from django.utils import timezone

from apps.accounts.models import User
from apps.ai.client import AIError, AIResult
from apps.companies.models import Company, Membership
from apps.jobs.models import Job
from apps.jobs.runner import claim_next, run_job
from apps.studio.designs import PHOTO_TEMPLATES, SCHEMES, V2_LAYOUTS

from .models import ContentPlan, Post
from .services import apply_plan


def make_company(name='شركة', **kwargs):
    defaults = dict(industry='تقنية', country='قطر', description='وصف', timezone='Asia/Qatar')
    defaults.update(kwargs)
    company = Company.objects.create(name=name, **defaults)
    # Paid jobs are charged when queued: give the test company a balance that never runs out.
    from apps.credits.models import Wallet
    Wallet.objects.create(company=company, balance=10_000_000)
    return company


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
         'template': 'gradient', 'caption': 'نص', 'hashtags': '#وسم', 'visual_notes': '', 'video_script': '',
         'vectors': ['rocket', 'rocket', 'nope', 'gift', 'star', 'heart']},
        # Out-of-range day, bad time, unknown template, a platform outside the plan, a script on an image post.
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
        self.assertEqual(first.vectors, ['rocket', 'gift', 'star'])  # deduplicated, valid, at most three
        self.assertIn(first.template, V2_LAYOUTS)  # the plan's older layout name is replaced by one that fits the content
        self.assertEqual(first.size, Post.Size.PORTRAIT)

    def test_sanitises_bad_values(self):
        apply_plan(self.plan, PLAN_DATA)
        tiktok = Post.objects.get(headline='فيديو')
        self.assertEqual(tiktok.scheduled_at.astimezone(self.company.tzinfo).day, 28)  # clamped to Feb 28
        self.assertEqual(tiktok.platforms, ['tiktok'])
        self.assertEqual(tiktok.format, Post.Format.IMAGE)  # a TikTok photo post, not forced to video
        self.assertEqual(tiktok.size, Post.Size.STORY)
        self.assertEqual(tiktok.video_script, '')
        self.assertIn(tiktok.template, V2_LAYOUTS)  # 'neon' is unknown: art direction picks a real layout
        self.assertIn(tiktok.scheme, SCHEMES)
        self.assertEqual(tiktok.title, 'فيديو')

    def test_posts_get_varied_art_direction_and_the_brands_photos(self):
        import io
        import tempfile

        from django.core.files.uploadedfile import SimpleUploadedFile
        from PIL import Image

        from apps.companies.models import MediaAsset
        buf = io.BytesIO()
        Image.new('RGB', (4, 4), '#6d5ef8').save(buf, 'PNG')
        with override_settings(MEDIA_ROOT=tempfile.mkdtemp()):
            MediaAsset.objects.create(company=self.company, file=SimpleUploadedFile('a.png', buf.getvalue(), 'image/png'))
        item = PLAN_DATA['posts'][0]
        kinds = [{'headline': 'خدمات تقنية لعملك'}, {'headline': 'ثلاث خطوات للبدء', 'subheadline': 'نفهم\nنصمم\nنطلق'},
                 {'headline': 'جمعة مباركة'}, {'headline': 'ما أكبر تحدٍّ يواجه عملك؟'}, {'headline': 'خصم خاص', 'badge': '30%'},
                 {'headline': 'خبرة سنوات', 'badge': '9 سنوات'}, {'headline': 'فريق يبني حلولاً', 'template': 'cover'}]
        data = {**PLAN_DATA, 'posts': [{**item, 'day': d, 'title': f'م{d}', 'template': 'cover', **kinds[d % len(kinds)]} for d in range(1, 13)]}
        apply_plan(self.plan, data)  # bulk_create: MySQL doesn't hand back primary keys, so query the plan's posts
        posts = Post.objects.filter(plan=self.plan).order_by('scheduled_at')
        layouts = [p.template for p in posts]
        self.assertGreaterEqual(len(set(layouts)), 5)  # twelve "cover" suggestions do not become twelve photo posts
        self.assertTrue(all(a != b for a, b in zip(layouts, layouts[1:])))
        self.assertTrue(all(p.background_id for p in posts if p.template in PHOTO_TEMPLATES))

    def test_reels_keep_their_script(self):
        data = {**PLAN_DATA, 'posts': [{**PLAN_DATA['posts'][1], 'format': 'reel', 'day': 3}]}
        reel = apply_plan(self.plan, data)[0]
        self.assertEqual((reel.format, reel.size, reel.video_script), (Post.Format.REEL, Post.Size.STORY, 'مشهد'))

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
        call_json.return_value = AIResult(data=PLAN_DATA, input_tokens=1000, output_tokens=2000,
                                          cache_hit_tokens=600, model='deepseek-v4-pro')
        job = run_job(claim_next())
        self.assertEqual(job.status, Job.Status.DONE, job.error)
        self.assertEqual((job.input_tokens, job.output_tokens, job.cache_hit_tokens), (1000, 2000, 600))
        self.assertEqual(job.model, 'deepseek-v4-pro')
        self.assertGreater(job.cost_usd, 0)
        self.plan.refresh_from_db()
        self.assertEqual(self.plan.status, ContentPlan.Status.READY)
        self.assertTrue(Job.objects.filter(kind=Job.Kind.RENDER_PLAN, status=Job.Status.PENDING).exists())

    @override_settings(AI_ENABLED=False)
    def test_without_key_fails_with_readable_message(self):
        job = run_job(claim_next())
        self.assertEqual(job.status, Job.Status.FAILED)
        self.assertNotIn('secrets.json', job.error)
        self.assertIn('secrets.json', job.error_detail)
        self.plan.refresh_from_db()
        self.assertEqual(self.plan.status, ContentPlan.Status.FAILED)
        self.assertNotIn('secrets.json', self.plan.error)

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

    def test_manual_publish_card_links_the_posts_platforms(self):
        self.post.platforms = ['facebook', 'tiktok', 'instagram']
        self.post.status = Post.Status.APPROVED
        self.post.save()
        self.client.force_login(self.owner)
        r = self.client.get(reverse('content:post_edit', args=[self.post.pk]))
        self.assertContains(r, 'id="manualPublish"')
        self.assertNotContains(r, 'mt-3 d-none" id="manualPublish"')
        self.assertContains(r, 'https://business.facebook.com/latest/composer', count=2)  # Facebook and Instagram
        self.assertContains(r, 'https://www.tiktok.com/tiktokstudio/upload', count=1)

    def test_manual_publish_card_hidden_until_approved(self):
        self.client.force_login(self.owner)
        r = self.client.get(reverse('content:post_edit', args=[self.post.pk]))
        self.assertContains(r, 'mt-3 d-none" id="manualPublish"')

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

    def editor_data(self, **extra):
        return {'title': 'منشور', 'platforms': ['facebook'], 'format': 'image', 'scheduled_at': '2026-04-02T18:45',
                'headline': 'قديم', 'template': 'bold', 'size': 'square', **extra}

    def test_editor_saves_colour_scheme_motif_and_variant(self):
        self.client.force_login(self.editor)
        r = self.client.post(reverse('content:post_edit', args=[self.post.pk]),
                             self.editor_data(scheme='dark', motif='confetti', variant='4242'))
        self.assertEqual(r.status_code, 200, r.content)
        self.assertIsNotNone(r.json()['render_job'])  # only the look changed, the image is still redrawn
        self.post.refresh_from_db()
        self.assertEqual((self.post.scheme, self.post.motif, self.post.variant), ('dark', 'confetti', 4242))

    def test_blank_variant_keeps_the_saved_one_and_bad_choices_are_refused(self):
        Post.objects.filter(pk=self.post.pk).update(variant=77)
        self.client.force_login(self.editor)
        r = self.client.post(reverse('content:post_edit', args=[self.post.pk]), self.editor_data(scheme='', motif='', variant=''))
        self.assertEqual(r.status_code, 200, r.content)
        self.post.refresh_from_db()
        self.assertEqual((self.post.scheme, self.post.motif, self.post.variant), ('', '', 77))
        r = self.client.post(reverse('content:post_edit', args=[self.post.pk]), self.editor_data(scheme='neon'))
        self.assertEqual(r.status_code, 400)

    def test_editor_page_offers_the_design_pickers(self):
        self.client.force_login(self.editor)
        html = self.client.get(reverse('content:post_edit', args=[self.post.pk])).content.decode()
        self.assertIn('id="shuffleBtn"', html)
        self.assertEqual(html.count('data-scheme='), 10)  # auto + nine schemes
        self.assertEqual(html.count('data-template='), len(V2_LAYOUTS) + 1)  # the new layouts, plus the older one this post still uses

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


class OverdueVisibilityTests(TestCase):
    """The dashboard's "overdue" alert leads to the posts it counts, and the calendar marks them."""

    def setUp(self):
        self.company = make_company()
        self.client.force_login(make_user('o@x.test', self.company))
        now = timezone.now()
        self.late = Post.objects.create(company=self.company, title='متأخر', platforms=['facebook'],
                                        status=Post.Status.APPROVED, scheduled_at=now - datetime.timedelta(days=2))
        self.future = Post.objects.create(company=self.company, title='قادم', platforms=['facebook'],
                                          status=Post.Status.APPROVED, scheduled_at=now + datetime.timedelta(days=2))
        self.done = Post.objects.create(company=self.company, title='منشور', platforms=['facebook'],
                                        status=Post.Status.PUBLISHED, scheduled_at=now - datetime.timedelta(days=3))

    def test_list_filter_shows_only_overdue_posts(self):
        response = self.client.get(reverse('content:post_list'), {'overdue': '1'})
        self.assertEqual([p.title for p in response.context['page'].object_list], ['متأخر'])
        self.assertEqual(self.client.get(reverse('content:post_list')).context['page'].paginator.count, 3)

    def test_dashboard_alert_links_to_the_overdue_list(self):
        response = self.client.get(reverse('core:dashboard'))
        self.assertContains(response, reverse('content:post_list') + '?overdue=1')

    def test_calendar_marks_overdue_chips_only(self):
        month = timezone.localtime(self.late.scheduled_at).strftime('%Y-%m')
        response = self.client.get(reverse('content:calendar'), {'month': month})
        cells = [c for week in response.context['weeks'] for c in week]
        flags = {p.title: p.is_overdue for c in cells for p in c['posts']}
        self.assertTrue(flags.get('متأخر'))
        self.assertFalse(flags.get('منشور', False))
        self.assertContains(response, 'is-overdue')
