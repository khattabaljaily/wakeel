"""Announcements: managers publish, the team (not the author, not a client) is told and reads; confirmations; who read it."""
from django.conf import settings
from django.test import TestCase
from django.urls import reverse

from apps.companies.models import Membership
from apps.content.tests import make_company, make_user
from apps.notifications.models import Notification

from .models import Announcement, AnnouncementRead


class Base(TestCase):
    def setUp(self):
        self.company = make_company('Alpha')
        self.other = make_company('Beta')
        self.owner = make_user('owner@example.com', self.company)
        self.admin = make_user('admin@example.com', self.company, Membership.Role.ADMIN)
        self.member = make_user('member@example.com', self.company, Membership.Role.EDITOR)
        self.viewer = make_user('viewer@example.com', self.company, Membership.Role.VIEWER)
        self.outsider = make_user('client@example.com', self.company, Membership.Role.CLIENT)
        self.client.cookies[settings.LANGUAGE_COOKIE_NAME] = 'en'
        self.client.force_login(self.owner)

    def publish(self, **kw):
        data = {'kind': 'circular', 'title': 'Office closed Friday', 'body': 'Back on Sunday.'}
        data.update(kw)
        self.client.post(reverse('announcements:new'), data)
        return Announcement.all_companies.filter(company=self.company).order_by('-id').first()

    def told(self, user):
        return [n.kind for n in Notification.objects.filter(user=user, company=self.company)]

    def reads(self):
        return AnnouncementRead.all_companies.filter(company=self.company)


class Publishing(Base):
    def test_a_manager_publishes_and_the_team_but_not_the_author_or_a_client_is_told(self):
        a = self.publish()
        self.assertEqual((a.author, a.kind, a.company), (self.owner, 'circular', self.company))
        for person in (self.admin, self.member, self.viewer):
            self.assertEqual(self.told(person), ['announcement'])
        self.assertEqual((self.told(self.owner), self.told(self.outsider)), ([], []))

    def test_asking_for_a_confirmation_changes_what_they_are_told(self):
        self.publish(requires_ack='on')
        self.assertEqual(self.told(self.member), ['announcement_ack'])

    def test_a_refused_form_opens_again(self):
        page = self.client.post(reverse('announcements:new'), {'kind': 'notice', 'title': '', 'body': ''})
        self.assertContains(page, 'collapse show')
        self.assertFalse(Announcement.all_companies.exists())

    def test_members_read_but_never_publish_change_or_delete(self):
        a = self.publish()
        for who in (self.member, self.viewer):
            self.client.force_login(who)
            self.assertEqual(self.client.get(reverse('announcements:list')).status_code, 200)
            self.assertNotContains(self.client.get(reverse('announcements:list')), 'id="newAnnouncement"')
            self.assertEqual(self.client.post(reverse('announcements:new'), {'kind': 'notice', 'title': 'x', 'body': 'y'}).status_code, 403)
            self.assertEqual(self.client.get(reverse('announcements:edit', args=[a.pk])).status_code, 403)
            self.assertEqual(self.client.post(reverse('announcements:delete', args=[a.pk])).status_code, 403)
        self.assertEqual(Announcement.all_companies.count(), 1)

    def test_a_client_is_outside_the_team_and_another_company_sees_nothing(self):
        a = self.publish()
        self.client.force_login(self.outsider)
        self.assertEqual(self.client.get(reverse('announcements:list')).status_code, 403)
        self.assertEqual(self.client.get(reverse('announcements:detail', args=[a.pk])).status_code, 403)
        self.client.force_login(make_user('s@example.com', self.other))
        self.assertEqual(self.client.get(reverse('announcements:detail', args=[a.pk])).status_code, 404)
        self.assertEqual(self.client.post(reverse('announcements:confirm', args=[a.pk])).status_code, 404)
        self.assertEqual(len(self.client.get(reverse('announcements:list')).context['items']), 0)


class Reading(Base):
    def test_opening_it_is_reading_it_and_reads_its_notification(self):
        a = self.publish()
        self.client.force_login(self.member)
        self.assertEqual(self.client.get(reverse('announcements:list')).context['unread'], 1)
        self.client.get(reverse('announcements:detail', args=[a.pk]))
        self.assertTrue(self.reads().filter(announcement=a, user=self.member).exists())
        self.assertEqual(self.client.get(reverse('announcements:list')).context['unread'], 0)
        self.assertIsNotNone(Notification.objects.get(user=self.member).read_at)

    def test_confirming_is_once_and_only_when_it_was_asked_for(self):
        plain, asked = self.publish(title='Plain'), self.publish(title='Asked', requires_ack='on')
        self.client.force_login(self.member)
        self.client.post(reverse('announcements:confirm', args=[plain.pk]))
        self.assertFalse(self.reads().filter(announcement=plain).exists())
        page = self.client.get(reverse('announcements:detail', args=[asked.pk]))
        self.assertContains(page, reverse('announcements:confirm', args=[asked.pk]))
        self.client.post(reverse('announcements:confirm', args=[asked.pk]))
        first = self.reads().get(announcement=asked, user=self.member).acknowledged_at
        self.client.post(reverse('announcements:confirm', args=[asked.pk]))
        self.assertEqual(self.reads().get(announcement=asked).acknowledged_at, first)
        self.assertNotContains(self.client.get(reverse('announcements:detail', args=[asked.pk])), reverse('announcements:confirm', args=[asked.pk]))

    def test_only_managers_see_who_read_it(self):
        a = self.publish(requires_ack='on')
        self.client.force_login(self.member)
        self.client.get(reverse('announcements:detail', args=[a.pk]))
        self.client.post(reverse('announcements:confirm', args=[a.pk]))
        self.assertNotIn('rows', self.client.get(reverse('announcements:detail', args=[a.pk])).context)
        self.client.force_login(self.admin)
        context = self.client.get(reverse('announcements:detail', args=[a.pk])).context
        self.assertEqual((context['total'], context['read_count'], context['ack_count']), (3, 2, 1))   # admin, member, viewer
        self.client.force_login(self.owner)
        self.assertEqual(self.client.get(reverse('announcements:detail', args=[a.pk])).context['total'], 3)   # not the author

    def test_the_author_is_not_asked_to_read_their_own(self):
        a = self.publish(requires_ack='on')
        page = self.client.get(reverse('announcements:list'))
        self.assertEqual(page.context['unread'], 0)
        self.assertFalse(page.context['items'][0]['needs_ack'])
        self.client.get(reverse('announcements:detail', args=[a.pk]))
        self.assertFalse(self.reads().exists())
