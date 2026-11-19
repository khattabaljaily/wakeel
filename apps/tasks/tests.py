"""Tasks: create, assign (only to people who work in the company), status, files encrypted and only downloaded, notes,
notifications, who may do what, and isolation between companies."""
from django.conf import settings
from django.core.files.uploadedfile import SimpleUploadedFile
from django.test import TestCase
from django.urls import reverse

from apps.audit.models import AuditEvent
from apps.companies.models import Membership
from apps.content.tests import make_company, make_user
from apps.notifications.models import Notification

from .models import Task, TaskAttachment, TaskComment


class Base(TestCase):
    def setUp(self):
        self.company = make_company('Alpha')
        self.other = make_company('Beta')
        self.owner = make_user('owner@example.com', self.company)
        self.member = make_user('member@example.com', self.company, Membership.Role.EDITOR)
        self.viewer = make_user('viewer@example.com', self.company, Membership.Role.VIEWER)
        self.client.cookies[settings.LANGUAGE_COOKIE_NAME] = 'en'
        self.client.force_login(self.owner)

    def task(self, **kw):
        return Task.all_companies.create(company=self.company, title=kw.pop('title', 'Send the quote'), **kw)

    def tasks(self):
        return Task.all_companies.filter(company=self.company)


class TaskFlow(Base):
    def test_create_assign_and_finish(self):
        r = self.client.post(reverse('tasks:new'), {'title': 'Renew licence', 'assignee': self.member.pk,
                                                    'priority': 'high', 'due_date': '2030-01-01'})
        task = self.tasks().get()
        self.assertRedirects(r, reverse('tasks:detail', args=[task.pk]))
        self.assertEqual((task.assignee, task.created_by, task.company), (self.member, self.owner, self.company))
        self.client.post(reverse('tasks:status', args=[task.pk]), {'status': 'done'})
        task.refresh_from_db()
        self.assertTrue(task.is_done and task.completed_at)
        self.client.post(reverse('tasks:status', args=[task.pk]), {'status': 'todo'})
        task.refresh_from_db()
        self.assertIsNone(task.completed_at)
        self.assertEqual(AuditEvent.all_companies.filter(company=self.company, action__startswith='task.').count(), 3)

    def test_the_assignee_is_told_and_not_the_person_who_gave_it_to_themselves(self):
        self.client.post(reverse('tasks:new'), {'title': 'Renew licence', 'assignee': self.member.pk, 'priority': 'normal'})
        told = Notification.objects.get(user=self.member, kind='task_assigned')
        self.assertEqual((told.company, told.url), (self.company, reverse('tasks:detail', args=[self.tasks().get().pk])))
        self.client.post(reverse('tasks:new'), {'title': 'Mine', 'assignee': self.owner.pk, 'priority': 'normal'})
        self.assertFalse(Notification.objects.filter(user=self.owner).exists())

    def test_a_note_tells_the_assignee_and_the_creator_but_not_the_writer(self):
        task = self.task(assignee=self.member, created_by=self.owner)
        self.client.post(reverse('tasks:comment', args=[task.pk]), {'body': 'Sent it'})
        self.assertEqual(TaskComment.all_companies.get().body, 'Sent it')
        self.assertEqual(list(Notification.objects.filter(kind='task_comment').values_list('user', flat=True)), [self.member.pk])

    def test_a_viewer_a_client_or_someone_of_another_company_cannot_be_given_a_task(self):
        client = make_user('client@example.com', self.company, Membership.Role.CLIENT)
        stranger = make_user('s@example.com', self.other)
        for person in (self.viewer, client, stranger):
            r = self.client.post(reverse('tasks:new'), {'title': 'x', 'assignee': person.pk, 'priority': 'normal'})
            self.assertEqual(r.status_code, 200)
        self.assertFalse(self.tasks().exists())

    def test_list_filters(self):
        mine = self.task(title='Mine', assignee=self.owner)
        self.task(title='Theirs', assignee=self.member)
        done = self.task(title='Finished')
        done.set_status('done')
        done.save()
        self.assertEqual([t.pk for t in self.client.get(reverse('tasks:list'), {'show': 'mine'}).context['tasks']], [mine.pk])
        self.assertEqual(len(self.client.get(reverse('tasks:list')).context['tasks']), 2)
        self.assertEqual(len(self.client.get(reverse('tasks:list'), {'show': 'done'}).context['tasks']), 1)

    def test_a_refused_form_opens_again_with_its_errors(self):
        page = self.client.post(reverse('tasks:new'), {'title': '', 'priority': 'normal'})
        self.assertContains(page, 'collapse show')
        self.assertTrue(page.context['form'].errors)


class Permissions(Base):
    def test_viewer_reads_but_cannot_write(self):
        task = self.task()
        self.client.force_login(self.viewer)
        self.assertEqual(self.client.get(reverse('tasks:list')).status_code, 200)
        self.assertNotContains(self.client.get(reverse('tasks:list')), 'id="newTask"')
        self.assertEqual(self.client.get(reverse('tasks:detail', args=[task.pk])).status_code, 200)
        self.client.post(reverse('tasks:new'), {'title': 'x', 'priority': 'normal'})
        self.client.post(reverse('tasks:status', args=[task.pk]), {'status': 'done'})
        self.client.post(reverse('tasks:comment', args=[task.pk]), {'body': 'hi'})
        task.refresh_from_db()
        self.assertEqual((self.tasks().count(), task.status, TaskComment.all_companies.count()), (1, Task.TODO, 0))

    def test_an_outside_client_of_the_company_sees_no_tasks(self):
        task = self.task()
        self.client.force_login(make_user('client@example.com', self.company, Membership.Role.CLIENT))
        self.assertEqual(self.client.get(reverse('tasks:list')).status_code, 403)
        self.assertEqual(self.client.get(reverse('tasks:detail', args=[task.pk])).status_code, 403)

    def test_only_the_creator_or_a_manager_deletes(self):
        task = self.task(created_by=self.owner)
        self.client.force_login(self.member)
        self.assertEqual(self.client.post(reverse('tasks:delete', args=[task.pk])).status_code, 403)
        self.assertTrue(self.tasks().filter(pk=task.pk).exists())
        own = self.task(created_by=self.member)
        self.client.post(reverse('tasks:delete', args=[own.pk]))
        self.assertFalse(self.tasks().filter(pk=own.pk).exists())
        self.client.force_login(self.owner)
        self.client.post(reverse('tasks:delete', args=[task.pk]))
        self.assertFalse(self.tasks().filter(pk=task.pk).exists())

    def test_another_company_sees_nothing(self):
        task = self.task()
        attachment = TaskAttachment(company=self.company, task=task, name='a.txt', size=1)
        attachment.file.save('a.txt', SimpleUploadedFile('a.txt', b'x'), save=False)
        attachment.save()
        self.client.force_login(make_user('stranger@example.com', self.other))
        self.assertEqual(self.client.get(reverse('tasks:detail', args=[task.pk])).status_code, 404)
        self.assertEqual(self.client.get(reverse('tasks:file', args=[attachment.pk])).status_code, 404)
        self.assertEqual(self.client.post(reverse('tasks:status', args=[task.pk]), {'status': 'done'}).status_code, 404)
        self.assertEqual(self.client.post(reverse('tasks:delete', args=[task.pk])).status_code, 404)
        self.assertEqual(self.client.post(reverse('tasks:file_delete', args=[attachment.pk])).status_code, 404)
        self.assertNotContains(self.client.get(reverse('tasks:list')), 'Send the quote')


class Files(Base):
    def test_attachment_is_encrypted_and_only_downloaded(self):
        task = self.task()
        self.client.post(reverse('tasks:attach', args=[task.pk]),
                         {'file': SimpleUploadedFile('plan.html', b'<script>alert(1)</script>', 'text/html')})
        attachment = TaskAttachment.all_companies.get()
        r = self.client.get(reverse('tasks:file', args=[attachment.pk]))
        self.assertEqual(b''.join(r.streaming_content), b'<script>alert(1)</script>')
        self.assertEqual(r['Content-Type'], 'application/octet-stream')
        self.assertIn('attachment', r['Content-Disposition'])
        with open(attachment.file.path, 'rb') as raw:
            self.assertNotIn(b'alert', raw.read())                     # encrypted on disk
        self.client.post(reverse('tasks:file_delete', args=[attachment.pk]))
        self.assertFalse(TaskAttachment.all_companies.exists())

    def test_too_big_is_refused(self):
        task = self.task()
        big = SimpleUploadedFile('big.bin', b'x' * (10 * 1024 * 1024 + 1))
        self.client.post(reverse('tasks:attach', args=[task.pk]), {'file': big})
        self.assertFalse(TaskAttachment.all_companies.exists())

    def test_deleting_a_task_removes_its_files(self):
        task = self.task(created_by=self.owner)
        self.client.post(reverse('tasks:attach', args=[task.pk]), {'file': SimpleUploadedFile('a.txt', b'hello')})
        path = TaskAttachment.all_companies.get().file.path
        self.client.post(reverse('tasks:delete', args=[task.pk]))
        import os
        self.assertFalse(os.path.exists(path))
