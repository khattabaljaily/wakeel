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
from apps.notifications.models import Notification
from apps.social import meta
from apps.social.meta import MetaError
from apps.social.models import SocialAccount

from . import services
from .models import InboxItem


def comment(cid, text, author='سارة', author_id='u1'):
    return {'id': cid, 'author': author, 'author_id': author_id, 'text': text, 'time': '2026-10-01T10:00:00+0000'}


class InboxTests(TestCase):
    def setUp(self):
        self.company = make_company(phone='+97455551234')
        self.owner = make_user('o@example.com', self.company)
        SocialAccount.objects.create(company=self.company, platform='facebook', external_id='PAGE', name='صفحتنا', access_token='tok')
        now = timezone.now()
        self.post = Post.objects.create(company=self.company, title='عرض الخريف', platforms=['facebook'], status=Post.Status.PUBLISHED,
                                        published_at=now - datetime.timedelta(days=2), external_ids={'facebook': 'PAGE_1'})

    def fetch(self, comments):
        with mock.patch.object(meta, 'facebook_comments', return_value=comments):
            return services.fetch(self.company)

    def triage(self, rows):
        with mock.patch('apps.ai.inbox.call_json', return_value=AIResult({'items': rows}, 5, 5, 0, 'm')) as call:
            services.triage(self.company)
        return call

    def test_fetch_stores_new_comments_once_and_skips_the_brands_own(self):
        new, problems = self.fetch([comment('c1', 'كم السعر؟'), comment('c2', 'شكراً لكم', author_id='PAGE')])
        self.assertEqual(([i.external_id for i in new], problems), (['c1'], []))
        new, _ = self.fetch([comment('c1', 'كم السعر؟')])
        self.assertEqual(new, [])
        self.assertEqual(InboxItem.objects.get().post, self.post)

    def test_triage_reads_labels_and_alerts_on_crises(self):
        self.fetch([comment('c1', 'هذا احتيال! سأشتكي للجهات'), comment('c2', 'رائع')])
        a, b = InboxItem.objects.order_by('external_id')
        call = self.triage([
            {'id': a.pk, 'sentiment': 'negative', 'category': 'complaint', 'urgency': 'crisis', 'reply': 'نعتذر، راسلنا على الخاص'},
            {'id': b.pk, 'sentiment': 'positive', 'category': 'praise', 'urgency': 'low', 'reply': 'شكراً لك!'},
        ])
        self.assertIn('هذا احتيال', call.call_args[0][1])
        a.refresh_from_db()
        self.assertEqual((a.urgency, a.suggested_reply, a.triaged), ('crisis', 'نعتذر، راسلنا على الخاص', True))
        self.assertEqual(Notification.objects.filter(user=self.owner).count(), 1)  # only the crisis
        self.assertEqual(len(mail.outbox), 1)
        self.assertEqual(InboxItem.objects.get(pk=b.pk).status, InboxItem.Status.NEW)  # auto-reply is off

    def test_auto_reply_answers_simple_ones_only(self):
        self.company.inbox_auto_reply = True
        self.company.save()
        self.fetch([comment('c1', 'متى تفتحون؟'), comment('c2', 'خدمة سيئة جداً')])
        q, bad = InboxItem.objects.order_by('external_id')
        with mock.patch.object(meta, 'reply_facebook', return_value='r1') as send:
            self.triage([
                {'id': q.pk, 'sentiment': 'neutral', 'category': 'question', 'urgency': 'normal', 'reply': 'من 9 صباحاً'},
                {'id': bad.pk, 'sentiment': 'negative', 'category': 'complaint', 'urgency': 'normal', 'reply': 'نعتذر'},
            ])
        send.assert_called_once_with('c1', 'tok', 'من 9 صباحاً')
        q.refresh_from_db()
        self.assertEqual((q.status, q.auto_replied), (InboxItem.Status.REPLIED, True))
        self.assertEqual(InboxItem.objects.get(pk=bad.pk).status, InboxItem.Status.NEW)

    def test_bad_ai_values_fall_back(self):
        self.fetch([comment('c1', 'x')])
        item = InboxItem.objects.get()
        self.triage([{'id': item.pk, 'sentiment': 'angry', 'category': 'x', 'urgency': 'apocalypse', 'reply': ''}])
        item.refresh_from_db()
        self.assertEqual((item.sentiment, item.category, item.urgency), ('neutral', 'other', 'normal'))

    def test_reply_from_the_page_and_errors_are_kept(self):
        self.fetch([comment('c1', 'كم السعر؟')])
        item = InboxItem.objects.get()
        self.client.force_login(self.owner)
        with mock.patch.object(meta, 'reply_facebook', side_effect=MetaError('رفضت Meta')):
            self.client.post(reverse('inbox:reply', args=[item.pk]), {'text': 'السعر في الرابط'})
        item.refresh_from_db()
        self.assertEqual((item.status, item.reply_error), (InboxItem.Status.NEW, 'رفضت Meta'))
        with mock.patch.object(meta, 'reply_facebook', return_value='r1') as send:
            self.client.post(reverse('inbox:reply', args=[item.pk]), {'text': 'السعر في الرابط'})
        send.assert_called_once_with('c1', 'tok', 'السعر في الرابط')
        item.refresh_from_db()
        self.assertEqual((item.status, item.replied_by), (InboxItem.Status.REPLIED, self.owner))

    def test_page_tabs_badge_and_dismiss(self):
        self.fetch([comment('c1', 'تعليق للعرض')])
        item = InboxItem.objects.get()
        self.client.force_login(self.owner)
        page = self.client.get(reverse('inbox:inbox'))
        self.assertContains(page, 'تعليق للعرض')
        self.assertContains(page, 'wk-nav__badge')
        self.client.post(reverse('inbox:dismiss', args=[item.pk]))
        self.assertEqual(InboxItem.objects.get().status, InboxItem.Status.DISMISSED)
        self.assertNotContains(self.client.get(reverse('inbox:inbox')), 'تعليق للعرض')

    def test_other_companies_items_are_hidden(self):
        other = make_company('أخرى')
        item = InboxItem.objects.create(company=other, platform='facebook', external_id='z', text='سر', received_at=timezone.now())
        self.client.force_login(self.owner)
        self.assertEqual(self.client.post(reverse('inbox:reply', args=[item.pk]), {'text': 'x'}).status_code, 404)

    def test_schedule_and_job(self):
        self.assertEqual(services.run_due(), 1)
        self.assertEqual(services.run_due(), 0)  # once per quarter hour
        with mock.patch.object(meta, 'facebook_comments', return_value=[comment('c1', 'سؤال')]), \
                mock.patch('apps.ai.inbox.call_json', return_value=AIResult({'items': []}, 1, 1, 0, 'm')):
            job = run_job(claim_next())
        self.assertEqual(job.status, Job.Status.DONE, job.error)
        self.assertEqual(InboxItem.objects.count(), 1)
