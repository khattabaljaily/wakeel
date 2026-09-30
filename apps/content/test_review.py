import datetime

from django.core import mail
from django.test import TestCase
from django.urls import reverse

from apps.companies.models import Membership
from apps.notifications.models import Notification

from .models import ContentPlan, Post, PostComment
from .tests import make_company, make_user


class ClientReviewTests(TestCase):
    def setUp(self):
        self.company = make_company()
        self.owner = make_user('owner@x.test', self.company)
        self.editor = make_user('editor@x.test', self.company, Membership.Role.EDITOR)
        self.plan = ContentPlan.objects.create(company=self.company, month=datetime.date(2026, 10, 1), platforms=['facebook'],
                                               status=ContentPlan.Status.READY, created_by=self.editor)
        self.post = Post.objects.create(company=self.company, plan=self.plan, title='منشور', platforms=['facebook'],
                                        caption='نص المنشور', status=Post.Status.REVIEW, created_by=self.editor)
        PostComment.objects.create(post=self.post, user=self.owner, body='ملاحظة داخلية للفريق')

    def share(self, user=None, action='on'):
        self.client.force_login(user or self.owner)
        self.client.post(reverse('content:plan_share', args=[self.plan.pk]), {'action': action})
        self.client.logout()
        self.plan.refresh_from_db()
        return reverse('review:plan', args=[self.plan.share_token]) if self.plan.share_token else None

    def feedback(self, action, body='', name='سارة'):
        return self.client.post(reverse('review:feedback', args=[self.plan.share_token, self.post.pk]),
                                {'action': action, 'name': name, 'body': body}, content_type='application/json')

    def test_link_off_by_default_and_only_managers_turn_it_on(self):
        self.assertEqual(self.plan.share_token, '')
        self.assertIsNone(self.share(self.editor))
        self.assertIsNotNone(self.share(self.owner))

    def test_client_sees_posts_but_not_internal_comments(self):
        response = self.client.get(self.share())
        self.assertContains(response, 'نص المنشور')
        self.assertNotContains(response, 'ملاحظة داخلية')

    def test_client_approves(self):
        self.share()
        self.assertEqual(self.feedback('approve').status_code, 200)
        self.post.refresh_from_db()
        self.assertEqual(self.post.status, Post.Status.APPROVED)
        self.assertTrue(PostComment.objects.filter(post=self.post, guest_name='سارة', kind='approval').exists())
        self.assertEqual(set(Notification.objects.values_list('user__email', flat=True)), {'owner@x.test', 'editor@x.test'})
        self.assertEqual(len(mail.outbox), 2)

    def test_client_requests_changes(self):
        self.share()
        self.feedback('changes', 'غيّروا اللون')
        self.post.refresh_from_db()
        self.assertEqual(self.post.status, Post.Status.DRAFT)
        self.assertIn('غيّروا اللون', self.post.review_note)

    def test_name_and_note_required(self):
        self.share()
        self.assertEqual(self.feedback('approve', name='').status_code, 400)
        self.assertEqual(self.feedback('changes', body='').status_code, 400)

    def test_revoked_or_regenerated_link_stops_working(self):
        old = self.share()
        self.share(action='new')
        self.assertEqual(self.client.get(old).status_code, 404)
        self.share(action='off')
        self.assertEqual(self.client.get(old).status_code, 404)
        self.assertEqual(self.client.get('/review/x/').status_code, 404)

    def test_post_from_another_plan_is_not_reachable(self):
        self.share()
        other = Post.objects.create(company=self.company, title='آخر', platforms=['facebook'])
        response = self.client.post(reverse('review:feedback', args=[self.plan.share_token, other.pk]),
                                    {'action': 'approve', 'name': 'س'}, content_type='application/json')
        self.assertEqual(response.status_code, 404)
