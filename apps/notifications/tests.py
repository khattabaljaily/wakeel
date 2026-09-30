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
