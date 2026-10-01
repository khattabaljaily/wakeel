import datetime
import io
import os
import shutil
import tempfile
from unittest import mock

from django.core.files.base import ContentFile
from django.test import TestCase, override_settings
from django.urls import reverse
from django.utils import timezone
from PIL import Image

from apps.companies.models import Membership
from apps.content.models import Post
from apps.content.tests import make_company, make_user
from apps.jobs.models import Job
from apps.jobs.runner import claim_next, run_job
from apps.notifications.models import Notification

from .models import SocialAccount
from .services import enqueue_due

MEDIA = tempfile.mkdtemp()


def png():
    buf = io.BytesIO()
    Image.new('RGBA', (8, 8), '#6d5ef8').save(buf, 'PNG')
    return buf.getvalue()


class FakeGraph:
    """Stands in for requests.request against graph.facebook.com; records every call."""

    def __init__(self, fail=None):
        self.calls, self.fail = [], fail or {}

    def __call__(self, method, url, **kwargs):
        path = url.split('/v23.0/', 1)[1]
        self.calls.append((method, path, kwargs))
        for key, error in self.fail.items():
            if key in path:
                return self.reply({'error': error}, 400)
        routes = {
            'oauth/access_token': {'access_token': 'user-token'},
            'me/accounts': {'data': [{'id': 'P1', 'name': 'صفحة إنجاز', 'access_token': 'page-token',
                                      'instagram_business_account': {'id': 'IG1', 'username': 'enjaz'}}]},
            'P1/photos': {'id': 'PH1', 'post_id': 'P1_99'},
            'IG1/media_publish': {'id': 'IGM1'},
            'IG1/media': {'id': 'C1'},
            'C1': {'status_code': 'FINISHED'},
        }
        for route in sorted(routes, key=len, reverse=True):
            if path.startswith(route):
                return self.reply(routes[route])
        raise AssertionError(f'unexpected call {method} {path}')

    @staticmethod
    def reply(body, status=200):
        response = mock.Mock(status_code=status)
        response.json.return_value = body
        return response


@override_settings(META_APP_ID='app', META_APP_SECRET='secret', META_ENABLED=True, META_GRAPH_VERSION='v23.0',
                   SITE_URL='https://app.wakeel.example')
class ConnectTests(TestCase):
    def setUp(self):
        self.company = make_company()
        self.owner = make_user('owner@x.test', self.company)
        self.client.force_login(self.owner)

    def start(self, popup=False):
        response = self.client.post(reverse('social:meta_connect'), {'popup': '1'} if popup else {})
        self.assertIn('facebook.com/v23.0/dialog/oauth', response.url)
        return self.client.session['wakeel_meta_state']['state']

    def callback(self, state, pages=None, **params):
        params = params or {'code': 'abc'}
        if pages is None:
            with mock.patch('apps.social.meta.requests.request', FakeGraph()):
                return self.client.get(reverse('social:meta_callback'), {'state': state, **params})
        with mock.patch('apps.social.views.pages_for_code', return_value=pages):
            return self.client.get(reverse('social:meta_callback'), {'state': state, **params})

    def result_page(self):
        return self.client.get(reverse('social:setup'), {'step': 'result'})

    def test_connects_page_and_instagram(self):
        response = self.callback(self.start())
        self.assertEqual(response.url, reverse('social:setup') + '?step=result')
        accounts = {a.platform: a for a in SocialAccount.objects.filter(company=self.company)}
        self.assertEqual((accounts['facebook'].external_id, accounts['facebook'].access_token), ('P1', 'page-token'))
        self.assertEqual((accounts['instagram'].external_id, accounts['instagram'].name), ('IG1', 'enjaz'))
        self.assertNotIn('wakeel_meta_pages', self.client.session)  # tokens don't linger in the session
        self.assertContains(self.result_page(), 'تم الربط بنجاح')

    def test_popup_tells_the_wizard_and_closes(self):
        response = self.callback(self.start(popup=True))
        self.assertContains(response, "BroadcastChannel('wakeel-meta')")
        self.assertNotContains(response, 'wk-sidebar')
        self.assertContains(self.result_page(), 'تم الربط بنجاح')

    def test_choosing_among_pages_stays_in_the_popup(self):
        pages = [{'id': f'P{i}', 'name': f'صفحة {i}', 'token': 't', 'instagram': {}} for i in (1, 2)]
        response = self.callback(self.start(popup=True), pages=pages)
        self.assertContains(response, 'wk-popup')
        response = self.client.post(reverse('social:meta_choose'), {'page': 'P2'})
        self.assertContains(response, "BroadcastChannel('wakeel-meta')")
        self.assertContains(self.result_page(), 'لم نجد حساب إنستغرام احترافي')

    def test_no_pages_offers_the_ways_out(self):
        self.callback(self.start(), pages=[])
        page = self.result_page()
        self.assertContains(page, 'لم يشارك فيسبوك أي صفحة')
        self.assertContains(page, reverse('companies:team'))

    def test_cancelled_or_closed_window_offers_a_retry(self):
        self.callback(self.start(), error='access_denied')
        self.assertContains(self.result_page(), 'لم يكتمل الربط')
        self.start(popup=True)
        page = self.client.get(reverse('social:setup'), {'step': 'result', 'closed': '1'})
        self.assertContains(page, 'لم يكتمل الربط')

    def test_every_wizard_step_renders(self):
        for step in ('page', 'page-create', 'instagram', 'ig-pro', 'ig-link', 'connect', 'result', 'bogus'):
            self.assertEqual(self.client.get(reverse('social:setup'), {'step': step}).status_code, 200, step)

    def test_rejects_wrong_state(self):
        self.start()
        with mock.patch('apps.social.meta.requests.request', FakeGraph()) as graph:
            self.client.get(reverse('social:meta_callback'), {'state': 'forged', 'code': 'abc'})
        self.assertFalse(graph.calls)
        self.assertFalse(SocialAccount.objects.exists())

    def test_editors_cannot_connect(self):
        editor = make_user('editor@x.test', self.company, Membership.Role.EDITOR)
        self.client.force_login(editor)
        self.assertEqual(self.client.post(reverse('social:meta_connect')).status_code, 403)


@override_settings(MEDIA_ROOT=MEDIA, META_GRAPH_VERSION='v23.0', SITE_URL='https://app.wakeel.example')
class PublishTests(TestCase):
    @classmethod
    def tearDownClass(cls):
        super().tearDownClass()
        shutil.rmtree(MEDIA, ignore_errors=True)

    def setUp(self):
        self.company = make_company(auto_publish=True)
        self.owner = make_user('owner@x.test', self.company)
        for platform, ext in (('facebook', 'P1'), ('instagram', 'IG1')):
            SocialAccount.objects.create(company=self.company, platform=platform, external_id=ext, name=ext,
                                         access_token='page-token')
        self.post = Post.objects.create(company=self.company, title='عرض', platforms=['facebook', 'instagram'],
                                        caption='نص', hashtags='#وسم', status=Post.Status.APPROVED, image_stale=False,
                                        scheduled_at=timezone.now() - datetime.timedelta(minutes=5))
        self.post.image.save('p.png', ContentFile(png()))

    def publish_via_api(self, graph):
        self.client.force_login(self.owner)
        response = self.client.post(reverse('api:post_publish', args=[self.post.pk]))
        self.assertEqual(response.status_code, 202, response.content)
        with mock.patch('apps.social.meta.requests.request', graph):
            return run_job(claim_next())

    def test_publishes_to_both_and_cleans_up(self):
        graph = FakeGraph()
        job = self.publish_via_api(graph)
        self.assertEqual(job.status, Job.Status.DONE, job.error)
        self.post.refresh_from_db()
        self.assertEqual(self.post.status, Post.Status.PUBLISHED)
        self.assertEqual(self.post.external_ids, {'facebook': 'P1_99', 'instagram': 'IGM1'})
        fb = next(c for c in graph.calls if c[1] == 'P1/photos')
        self.assertEqual(fb[2]['data']['message'], 'نص\n\n#وسم')
        ig = next(c for c in graph.calls if c[1] == 'IG1/media')
        self.assertTrue(ig[2]['data']['image_url'].startswith('https://app.wakeel.example/media/publish/'))
        self.assertTrue(ig[2]['data']['image_url'].endswith('.jpg'))
        self.assertEqual(os.listdir(os.path.join(MEDIA, 'publish')), [])  # temporary JPEG removed

    def test_expired_token_fails_readably_and_retry_skips_done_platform(self):
        job = self.publish_via_api(FakeGraph(fail={'IG1/media': {'code': 190, 'message': 'expired'}}))
        self.assertEqual(job.status, Job.Status.FAILED)
        self.assertIn('أعد ربط الحساب', job.error)
        self.post.refresh_from_db()
        self.assertEqual(self.post.status, Post.Status.APPROVED)
        self.assertEqual(self.post.external_ids, {'facebook': 'P1_99'})
        self.assertIn('أعد ربط', SocialAccount.objects.get(platform='instagram').last_error)
        self.assertTrue(Notification.objects.filter(user=self.owner, message__contains='تعذّر نشر').exists())

        graph = FakeGraph()
        self.assertEqual(self.publish_via_api(graph).status, Job.Status.DONE)
        self.assertFalse([c for c in graph.calls if c[1] == 'P1/photos'])  # Facebook not posted twice
        self.assertEqual(SocialAccount.objects.get(platform='instagram').last_error, '')

    def test_api_rules(self):
        editor = make_user('editor@x.test', self.company, Membership.Role.EDITOR)
        self.client.force_login(editor)
        self.assertEqual(self.client.post(reverse('api:post_publish', args=[self.post.pk])).status_code, 403)
        self.client.force_login(self.owner)
        Post.objects.filter(pk=self.post.pk).update(status=Post.Status.REVIEW)
        self.assertEqual(self.client.post(reverse('api:post_publish', args=[self.post.pk])).status_code, 400)
        Post.objects.filter(pk=self.post.pk).update(status=Post.Status.APPROVED, format=Post.Format.REEL)
        response = self.client.post(reverse('api:post_publish', args=[self.post.pk]))
        self.assertContains(response, 'يدوياً', status_code=400)

    def test_auto_publish_queues_due_posts_once(self):
        self.assertEqual(enqueue_due(), 1)
        self.assertEqual(enqueue_due(), 0)
        with mock.patch('apps.social.meta.requests.request', FakeGraph()):
            job = run_job(claim_next())
        self.assertEqual(job.status, Job.Status.DONE, job.error)

    def test_auto_publish_skips_off_late_unapproved_and_future(self):
        now = timezone.now()
        self.company.auto_publish = False
        self.company.save()
        self.assertEqual(enqueue_due(), 0)
        self.company.auto_publish = True
        self.company.save()
        for when, status in ((now - datetime.timedelta(hours=7), Post.Status.APPROVED),
                             (now + datetime.timedelta(hours=1), Post.Status.APPROVED),
                             (now - datetime.timedelta(minutes=1), Post.Status.REVIEW)):
            Post.objects.filter(pk=self.post.pk).update(scheduled_at=when, status=status)
            self.assertEqual(enqueue_due(), 0)

    def test_rescheduling_allows_another_automatic_attempt(self):
        enqueue_due()
        Job.objects.all().delete()
        self.client.force_login(self.owner)
        self.client.post(reverse('api:post_reschedule', args=[self.post.pk]),
                         {'date': timezone.localdate().isoformat()}, content_type='application/json')
        self.post.refresh_from_db()
        self.assertIsNone(self.post.publish_attempted_at)
