import datetime
from unittest import mock

from django.core import mail
from django.test import TestCase
from django.urls import reverse

from apps.ai.client import AIResult
from apps.companies.models import Membership
from apps.content.models import ContentPlan, Post, PostComment
from apps.content.tests import PLAN_DATA, make_company, make_user
from apps.jobs.models import Job
from apps.jobs.runner import claim_next, run_job

from .models import Notification


class ReviewNotificationTests(TestCase):
    def setUp(self):
        self.company = make_company()
        self.owner = make_user('owner@x.test', self.company)
        self.editor = make_user('editor@x.test', self.company, Membership.Role.EDITOR)
        self.viewer = make_user('viewer@x.test', self.company, Membership.Role.VIEWER)
        self.post = Post.objects.create(company=self.company, title='منشور', platforms=['facebook'],
                                        created_by=self.editor, status=Post.Status.DRAFT)

    def api(self, user, name, data, pk=None):
        self.client.force_login(user)
        return self.client.post(reverse(f'api:{name}', args=[pk or self.post.pk] if name != 'posts_bulk_status' else []),
                                data, content_type='application/json')

    def test_sending_for_review_tells_managers_not_the_sender(self):
        self.api(self.editor, 'post_status', {'status': 'review'})
        self.assertEqual(list(Notification.objects.values_list('user__email', flat=True)), ['owner@x.test'])
        self.assertEqual(len(mail.outbox), 0)  # in-app only

    def test_change_request_adds_thread_entry_and_emails_author(self):
        self.post.status = Post.Status.REVIEW
        self.post.save()
        self.api(self.owner, 'post_status', {'status': 'draft', 'note': 'غيّر الصورة'})
        comment = PostComment.objects.get(post=self.post)
        self.assertEqual((comment.kind, comment.body, comment.user), (PostComment.Kind.CHANGES, 'غيّر الصورة', self.owner))
        note = Notification.objects.get(user=self.editor)
        self.assertIn('غيّر الصورة', note.message)
        self.assertEqual([m.to for m in mail.outbox], [['editor@x.test']])

    def test_no_email_when_user_opted_out(self):
        self.editor.email_notifications = False
        self.editor.save()
        self.post.status = Post.Status.REVIEW
        self.post.save()
        self.api(self.owner, 'post_status', {'status': 'draft', 'note': 'عدّل'})
        self.assertTrue(Notification.objects.filter(user=self.editor).exists())
        self.assertEqual(len(mail.outbox), 0)

    def test_bulk_approval_sends_one_notification(self):
        second = Post.objects.create(company=self.company, title='ثانٍ', platforms=['facebook'], created_by=self.editor,
                                     status=Post.Status.REVIEW)
        self.api(self.owner, 'posts_bulk_status', {'status': 'approved', 'ids': [self.post.pk, second.pk]})
        notes = Notification.objects.filter(user=self.editor)
        self.assertEqual(notes.count(), 1)
        self.assertIn('2 منشورات', notes.get().message)

    def test_viewer_can_comment_and_team_hears_about_it(self):
        response = self.api(self.viewer, 'post_comment', {'body': 'العنوان طويل'})
        self.assertEqual(response.status_code, 201)
        self.assertEqual(set(Notification.objects.values_list('user__email', flat=True)), {'editor@x.test', 'owner@x.test'})

    def test_empty_comment_rejected(self):
        self.assertEqual(self.api(self.owner, 'post_comment', {'body': '  '}).status_code, 400)

    def test_open_marks_read_and_redirects(self):
        self.api(self.editor, 'post_status', {'status': 'review'})
        note = Notification.objects.get()
        self.client.force_login(self.owner)
        response = self.client.get(reverse('notifications:open', args=[note.pk]))
        self.assertRedirects(response, self.post.get_absolute_url(), fetch_redirect_response=False)
        note.refresh_from_db()
        self.assertIsNotNone(note.read_at)
        # Someone else's notification is not reachable.
        self.client.force_login(self.editor)
        self.assertEqual(self.client.get(reverse('notifications:open', args=[note.pk])).status_code, 404)

    def test_bell_shows_unread_count(self):
        self.api(self.editor, 'post_status', {'status': 'review'})
        self.client.force_login(self.owner)
        self.assertContains(self.client.get(reverse('core:dashboard')), 'wk-bell__count">1<')


class PlanNotificationTests(TestCase):
    @mock.patch('apps.ai.planner.call_json')
    def test_ready_plan_notifies_creator_and_managers_by_email(self, call_json):
        company = make_company()
        owner = make_user('owner@x.test', company)
        editor = make_user('editor@x.test', company, Membership.Role.EDITOR)
        plan = ContentPlan.objects.create(company=company, month=datetime.date(2026, 3, 1), platforms=['facebook', 'tiktok'],
                                          created_by=editor)
        Job.enqueue(company, Job.Kind.GENERATE_PLAN, editor, plan_id=plan.pk)
        call_json.return_value = AIResult(data=PLAN_DATA)
        run_job(claim_next())
        self.assertEqual(set(Notification.objects.values_list('user', flat=True)), {owner.pk, editor.pk})
        self.assertEqual(len(mail.outbox), 2)


class KindNotificationTests(TestCase):
    """Notifications by kind (from MyDocHub): the sentence is made when it is read, in the reader's language."""

    def setUp(self):
        from apps.notifications import registry
        self.registry = registry
        self.company = make_company()
        self.owner = make_user('owner@x.test', self.company)
        self.editor = make_user('editor@x.test', self.company, Membership.Role.EDITOR)
        self.viewer = make_user('viewer@x.test', self.company, Membership.Role.VIEWER)

    def test_each_reader_gets_the_sentence_in_their_language(self):
        from django.utils import translation

        from .services import notify_event
        self.editor.language = 'en'
        self.editor.save()
        notify_event([self.owner, self.editor], 'document_approved', company=self.company, title='Offer letter')
        owner_note = Notification.objects.get(user=self.owner)
        self.assertEqual((owner_note.kind, owner_note.params, owner_note.icon), ('document_approved', {'title': 'Offer letter'}, 'bi-check-circle'))
        with translation.override('en'):
            self.assertEqual(owner_note.text, 'Your document was approved: Offer letter')
        with translation.override('ar'):
            self.assertIn('Offer letter', owner_note.text)
            self.assertNotIn('Your document', owner_note.text)

    def test_old_marketing_notifications_still_read_as_their_message(self):
        note = Notification.objects.create(user=self.owner, company=self.company, message='خطة أكتوبر جاهزة')
        self.assertEqual(note.text, 'خطة أكتوبر جاهزة')
        self.client.force_login(self.owner)
        self.assertContains(self.client.get(reverse('notifications:list')), 'خطة أكتوبر جاهزة')

    def test_the_actor_is_not_told_and_a_dedupe_key_tells_a_person_once(self):
        from .services import notify_event
        self.assertEqual(notify_event([self.owner, self.editor], 'member_joined', company=self.company, actor=self.owner,
                                      who='Sara'), 1)
        self.assertFalse(Notification.objects.filter(user=self.owner).exists())
        for _ in range(2):
            notify_event(self.owner, 'expiring', company=self.company, dedupe_key='doc-1-30', title='Licence', date='2026-12-01')
        self.assertEqual(Notification.objects.filter(user=self.owner, kind='expiring').count(), 1)

    def test_managers_only_and_an_unknown_kind_is_refused(self):
        from .services import notify_managers_event
        self.assertEqual(notify_managers_event(self.company, 'wallet_low', balance='$1.50'), 1)
        self.assertEqual(Notification.objects.get().user, self.owner)
        with self.assertRaises(AssertionError):
            from .services import notify_event
            notify_event(self.owner, 'nonsense', company=self.company)

    def test_collectors_run_when_a_page_is_drawn_and_a_failing_one_is_harmless(self):
        from .services import notify_event
        seen = []

        def good(user, company):
            seen.append((user.pk, company.pk))
            notify_event(user, 'reminder', company=company, dedupe_key='r1', title='Call the bank')

        def bad(user, company):
            raise RuntimeError('boom')

        self.registry.COLLECTORS[:] = [bad, good]
        try:
            self.client.force_login(self.owner)
            self.assertEqual(self.client.get(reverse('core:dashboard')).status_code, 200)
            self.assertEqual(seen, [(self.owner.pk, self.company.pk)])
            self.assertEqual(Notification.objects.get(kind='reminder').user, self.owner)
        finally:
            self.registry.COLLECTORS[:] = []

    def test_prune_deletes_old_read_and_old_unread_ones_only(self):
        import datetime

        from django.utils import timezone

        from .services import prune
        now = timezone.now()
        old_read = Notification.objects.create(user=self.owner, company=self.company, message='a', read_at=now - datetime.timedelta(days=31))
        fresh_read = Notification.objects.create(user=self.owner, company=self.company, message='b', read_at=now - datetime.timedelta(days=5))
        old_unread = Notification.objects.create(user=self.owner, company=self.company, message='c')
        fresh_unread = Notification.objects.create(user=self.owner, company=self.company, message='d')
        Notification.objects.filter(pk=old_unread.pk).update(created_at=now - datetime.timedelta(days=91))
        self.assertEqual(prune(now), 2)
        self.assertEqual(set(Notification.objects.values_list('pk', flat=True)), {fresh_read.pk, fresh_unread.pk})
