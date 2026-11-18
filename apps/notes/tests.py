"""Personal notes: the owner's own (nobody else, not even the company owner), reminders at the owner's own clock, the bell and
the e-mail once, and a safe way back after a button."""
from datetime import timedelta

from django.conf import settings
from django.core import mail
from django.test import TestCase
from django.urls import reverse
from django.utils import timezone

from apps.companies.models import Membership
from apps.content.tests import make_company, make_user
from apps.notifications.models import Notification

from . import reminders
from .models import Note


class Base(TestCase):
    def setUp(self):
        self.company = make_company('Alpha')
        self.other = make_company('Beta')
        self.owner = make_user('owner@example.com', self.company)
        self.member = make_user('member@example.com', self.company, Membership.Role.EDITOR)
        self.client.cookies[settings.LANGUAGE_COOKIE_NAME] = 'en'
        self.client.force_login(self.member)

    def note(self, owner=None, **kw):
        return Note.all_companies.create(company=kw.pop('company', self.company), owner=owner or self.member,
                                         title=kw.pop('title', 'Call the bank'), **kw)

    def notes(self):
        return Note.all_companies.filter(company=self.company)


class Notebook(Base):
    def test_add_pin_done_and_delete(self):
        r = self.client.post(reverse('notes:new'), {'title': 'Buy toner', 'body': 'Black', 'tz': 'Africa/Khartoum'})
        self.assertRedirects(r, reverse('notes:list'))
        note = self.notes().get()
        self.assertEqual((note.owner, note.company, note.pinned, note.remind_at), (self.member, self.company, False, None))
        self.client.post(reverse('notes:pin', args=[note.pk]))
        note.refresh_from_db()
        self.assertTrue(note.pinned)
        self.client.post(reverse('notes:delete', args=[note.pk]))
        self.assertFalse(self.notes().exists())

    def test_the_reminder_is_the_owners_own_wall_clock_time(self):
        self.client.post(reverse('notes:new'), {'title': 'Stand-up', 'remind_date': '2030-05-01', 'remind_time': '09:00', 'tz': 'Africa/Khartoum'})
        note = self.notes().get()
        self.assertEqual(note.remind_at.isoformat(), '2030-05-01T07:00:00+00:00')          # Khartoum is UTC+2
        self.assertEqual(note.remind_display, '2030-05-01 09:00')
        page = self.client.get(reverse('notes:edit', args=[note.pk]))
        self.assertContains(page, 'value="2030-05-01"')
        self.assertContains(page, 'value="09:00"')                                          # edited as typed

    def test_a_bad_zone_falls_back_to_utc(self):
        self.client.post(reverse('notes:new'), {'title': 'x', 'remind_date': '2030-05-01', 'remind_time': '09:00', 'tz': 'Nowhere/Land'})
        self.assertEqual(self.notes().get().remind_at.isoformat(), '2030-05-01T09:00:00+00:00')

    def test_a_due_reminder_reaches_the_bell_once_and_a_new_time_makes_it_a_new_reminder(self):
        note = self.note(remind_at=timezone.now() - timedelta(minutes=5))
        self.client.get(reverse('notes:list'))
        self.client.get(reverse('notes:list'))
        told = Notification.objects.filter(user=self.member, kind='reminder')
        self.assertEqual((told.count(), told[0].company), (1, self.company))
        note.refresh_from_db()
        self.assertIsNotNone(note.notified_at)
        self.client.post(reverse('notes:done', args=[note.pk]))
        self.client.post(reverse('notes:edit', args=[note.pk]), {'title': 'Call the bank', 'remind_date': '2031-01-01', 'remind_time': '10:00', 'tz': 'UTC'})
        note.refresh_from_db()
        self.assertEqual((note.done, note.notified_at, note.reminded_at), (False, None, None))

    def test_the_way_back_after_a_button_stays_on_this_site(self):
        note = self.note()
        r = self.client.post(reverse('notes:pin', args=[note.pk]), {'next': '/app/notes/?show=reminders'})
        self.assertRedirects(r, '/app/notes/?show=reminders', fetch_redirect_response=False)
        for elsewhere in ('//evil.example/x', 'https://evil.example/', '/\\evil.example'):
            r = self.client.post(reverse('notes:pin', args=[note.pk]), {'next': elsewhere})
            self.assertRedirects(r, reverse('notes:list'), fetch_redirect_response=False, msg_prefix=elsewhere)

    def test_a_refused_form_opens_again(self):
        self.assertContains(self.client.post(reverse('notes:new'), {'title': ''}), 'collapse show')


class Privacy(Base):
    def test_nobody_else_sees_edits_or_deletes_a_note_not_even_the_company_owner(self):
        note = self.note()
        self.client.force_login(self.owner)
        self.assertEqual(len(self.client.get(reverse('notes:list')).context['notes']), 0)
        self.assertEqual(self.client.get(reverse('notes:edit', args=[note.pk])).status_code, 404)
        for name in ('pin', 'done', 'delete'):
            self.assertEqual(self.client.post(reverse(f'notes:{name}', args=[note.pk])).status_code, 404, name)
        self.assertTrue(self.notes().filter(pk=note.pk).exists())

    def test_my_notes_in_another_company_stay_there(self):
        Membership.objects.create(company=self.other, user=self.member, role=Membership.Role.EDITOR)
        self.note(company=self.other, title='Beta note')
        page = self.client.get(reverse('notes:list'))                        # working in Alpha
        self.assertNotContains(page, 'Beta note')

    def test_a_viewer_keeps_notes_too(self):
        viewer = make_user('viewer@example.com', self.company, Membership.Role.VIEWER)
        self.client.force_login(viewer)
        self.client.post(reverse('notes:new'), {'title': 'Mine', 'tz': 'UTC'})
        self.assertEqual(self.notes().get().owner, viewer)


class Email(Base):
    def test_a_due_reminder_is_mailed_once_and_is_in_the_bell_once(self):
        self.note(remind_at=timezone.now() - timedelta(minutes=1), body='Ask about the fees')
        self.note(title='Later', remind_at=timezone.now() + timedelta(days=1))
        self.note(title='Dismissed', remind_at=timezone.now() - timedelta(minutes=1), done=True)
        self.assertEqual(reminders.send_due(), 1)
        self.assertEqual(mail.outbox[0].to, ['member@example.com'])
        self.assertIn('Call the bank', mail.outbox[0].subject)
        self.assertIn('Ask about the fees', mail.outbox[0].body)
        self.assertEqual(reminders.send_due(), 0)
        self.assertEqual(Notification.objects.filter(user=self.member, kind='reminder').count(), 1)

    def test_a_member_who_turned_the_emails_off_gets_the_bell_only(self):
        self.member.email_notifications = False
        self.member.save()
        self.note(remind_at=timezone.now() - timedelta(minutes=1))
        self.assertEqual(reminders.send_due(), 0)
        self.assertEqual(len(mail.outbox), 0)
        self.assertEqual(Notification.objects.filter(user=self.member, kind='reminder').count(), 1)
        self.assertEqual(reminders.send_due(), 0)                     # not tried again and again

    def test_the_command_runs(self):
        from io import StringIO

        from django.core.management import call_command
        self.note(remind_at=timezone.now() - timedelta(minutes=1))
        out = StringIO()
        call_command('send_note_reminders', stdout=out)
        self.assertIn('1 reminder', out.getvalue())


class ReminderField(Base):
    def test_a_date_alone_is_for_nine_in_the_morning_and_a_time_alone_is_refused(self):
        self.client.post(reverse('notes:new'), {'title': 'a', 'remind_date': '2030-05-01', 'tz': 'UTC'})
        self.assertEqual(self.notes().get().remind_at.isoformat(), '2030-05-01T09:00:00+00:00')
        page = self.client.post(reverse('notes:new'), {'title': 'b', 'remind_time': '10:00', 'tz': 'UTC'})
        self.assertTrue(page.context['form'].errors['remind_date'])
        self.assertEqual(self.notes().count(), 1)

    def test_clearing_the_date_removes_the_reminder(self):
        note = self.note(remind_at=timezone.now() + timedelta(days=1))
        self.client.post(reverse('notes:edit', args=[note.pk]), {'title': 'Call the bank', 'tz': 'UTC'})
        note.refresh_from_db()
        self.assertIsNone(note.remind_at)
