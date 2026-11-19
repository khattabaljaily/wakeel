"""The dashboard's "waiting for you" panel: both halves of the product in one list, shaped by role, isolated by company."""
import datetime

from django.conf import settings
from django.core.files.base import ContentFile
from django.test import TestCase
from django.urls import reverse
from django.utils import timezone

from apps.companies.models import Membership
from apps.content.models import Post
from apps.content.tests import make_company, make_user
from apps.documents.models import Document
from apps.library.models import Record
from apps.library.tests import PDF
from apps.tasks.models import Task


class Waiting(TestCase):
    def setUp(self):
        self.company, self.other = make_company('Alpha'), make_company('Beta')
        self.owner = make_user('o@example.com', self.company)
        self.editor = make_user('e@example.com', self.company, Membership.Role.EDITOR)
        self.viewer = make_user('v@example.com', self.company, Membership.Role.VIEWER)
        self.client_user = make_user('c@example.com', self.company, Membership.Role.CLIENT)
        self.client.cookies[settings.LANGUAGE_COOKIE_NAME] = 'en'
        self.client.force_login(self.owner)

    def groups(self, user=None):
        if user:
            self.client.force_login(user)
        return {g['icon']: {i['url']: i['count'] for i in g['items']} for g in self.client.get(reverse('core:dashboard')).context['waiting']}

    def post(self, company, status, late=False):
        when = timezone.now() + datetime.timedelta(days=-2 if late else 2)
        return Post.objects.create(company=company, title='p', platforms=['facebook'], status=status, scheduled_at=when)

    def document(self, company, status):
        return Document.all_companies.create(company=company, title='d', category='letters', status=status)

    def record(self, company, days):
        r = Record(company=company, title='r', category='company', content_type='application/pdf',
                   expiry_date=timezone.localdate() + datetime.timedelta(days=days))
        r.file.save('r.pdf', ContentFile(PDF), save=False)
        r.save()

    def test_nothing_waiting_says_so(self):
        page = self.client.get(reverse('core:dashboard'))
        self.assertEqual(page.context['waiting'], [])
        self.assertContains(page, 'Nothing is waiting for you')

    def test_both_halves_appear_together(self):
        self.post(self.company, Post.Status.REVIEW)
        self.document(self.company, Document.PENDING)
        self.record(self.company, 5)
        Task.all_companies.create(company=self.company, title='t', assignee=self.owner, due_date=timezone.localdate() - datetime.timedelta(days=1))
        groups = self.groups()
        self.assertEqual(set(groups), {'bi-stars', 'bi-layers', 'bi-people'})
        self.assertEqual(groups['bi-layers'][reverse('documents:issued') + '?status=pending'], 1)
        self.assertEqual(groups['bi-layers'][reverse('library:list') + '?status=soon'], 1)
        self.assertEqual(groups['bi-people'][reverse('tasks:list') + '?show=mine'], 1)
        self.assertContains(self.client.get(reverse('core:dashboard')), 'Documents waiting for your approval')

    def test_late_posts_link_to_the_overdue_list(self):
        self.post(self.company, Post.Status.APPROVED, late=True)
        self.assertEqual(self.groups()['bi-stars'], {reverse('content:post_list') + '?overdue=1': 1})

    def test_only_the_owner_or_an_admin_is_asked_to_approve(self):
        self.document(self.company, Document.PENDING)
        self.assertIn('bi-layers', self.groups(self.owner))
        for user in (self.editor, self.viewer, self.client_user):
            self.assertNotIn('bi-layers', self.groups(user))

    def test_a_viewer_sees_no_review_work_and_a_client_no_internal_work(self):
        self.post(self.company, Post.Status.REVIEW)
        self.record(self.company, 3)
        Task.all_companies.create(company=self.company, title='t', assignee=self.client_user)
        self.assertEqual(self.groups(self.viewer).get('bi-stars'), None)
        self.assertEqual(self.groups(self.client_user), {})

    def test_my_tasks_only_and_done_ones_do_not_count(self):
        Task.all_companies.create(company=self.company, title='mine', assignee=self.editor)
        Task.all_companies.create(company=self.company, title='done', assignee=self.editor, status=Task.DONE)
        Task.all_companies.create(company=self.company, title='theirs', assignee=self.owner)
        self.assertEqual(self.groups(self.editor)['bi-people'], {reverse('tasks:list') + '?show=mine': 1})

    def test_another_companys_work_never_counts(self):
        self.post(self.other, Post.Status.REVIEW)
        self.document(self.other, Document.PENDING)
        self.record(self.other, 1)
        Task.all_companies.create(company=self.other, title='t', assignee=self.owner)
        self.assertEqual(self.groups(), {})

    def test_the_arabic_page_shows_the_panel_too(self):
        self.client.cookies[settings.LANGUAGE_COOKIE_NAME] = 'ar'
        self.post(self.company, Post.Status.REVIEW)
        self.post(self.company, Post.Status.APPROVED)
        self.document(self.company, Document.PENDING)
        page = self.client.get(reverse('core:dashboard'))
        self.assertContains(page, 'ينتظرك')
        self.assertContains(page, 'المستندات والملفات')                  # the group titles are translated too
        self.assertNotContains(page, 'Documents and files')
