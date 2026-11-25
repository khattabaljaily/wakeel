import datetime

from django.core import mail
from django.core.files.uploadedfile import SimpleUploadedFile
from django.test import TestCase
from django.urls import reverse
from django.utils import timezone

from apps.companies.models import Membership
from apps.content.tests import make_company, make_user
from apps.notifications.models import Notification

from . import reminders
from .models import Record

def _real_pdf():
    import io

    from pypdf import PdfWriter
    writer, out = PdfWriter(), io.BytesIO()
    writer.add_blank_page(width=200, height=200)
    writer.write(out)
    return out.getvalue()


PDF = _real_pdf()


def upload(name='licence.pdf', data=PDF):
    return SimpleUploadedFile(name, data, content_type='application/pdf')


class LibraryTests(TestCase):
    def setUp(self):
        self.company = make_company('A')
        self.other = make_company('B')
        self.owner = make_user('o@example.com', self.company)
        self.viewer = make_user('v@example.com', self.company, Membership.Role.VIEWER)
        self.stranger = make_user('s@example.com', self.other)

    def add(self, **kwargs):
        data = {'title': 'Licence', 'category': Record.COMPANY, 'file': upload()}
        data.update(kwargs)
        return self.client.post(reverse('library:upload'), data)

    def test_upload_stores_encrypted_file_and_detects_type(self):
        self.client.force_login(self.owner)
        response = self.add()
        record = Record.all_companies.get()
        self.assertRedirects(response, f"{reverse('library:list')}?rec={record.pk}")
        self.assertEqual((record.company, record.content_type, record.uploaded_by), (self.company, 'application/pdf', self.owner))
        with open(record.file.path, 'rb') as raw:
            self.assertNotIn(b'%PDF', raw.read())          # encrypted on disk
        self.assertEqual(self.client.get(reverse('library:file', args=[record.pk])).getvalue()[:5], b'%PDF-')

    def test_rejects_a_file_that_only_claims_to_be_a_pdf(self):
        self.client.force_login(self.owner)
        self.add(file=upload('x.pdf', b'<html>not a pdf</html>'))
        self.assertFalse(Record.all_companies.exists())

    def test_another_company_cannot_see_or_open_it(self):
        self.client.force_login(self.owner)
        self.add()
        record = Record.all_companies.get()
        self.client.force_login(self.stranger)
        self.assertEqual(self.client.get(reverse('library:file', args=[record.pk])).status_code, 404)
        self.assertEqual(self.client.get(reverse('library:edit', args=[record.pk])).status_code, 404)
        self.assertNotContains(self.client.get(reverse('library:list')), 'Licence')

    def test_roles(self):
        self.client.force_login(self.owner)
        self.add()
        record = Record.all_companies.get()
        self.client.force_login(self.viewer)
        self.assertContains(self.client.get(reverse('library:list')), 'Licence')       # a viewer reads
        self.assertEqual(self.client.get(reverse('library:upload')).status_code, 302)  # but never writes
        self.assertEqual(self.client.post(reverse('library:delete', args=[record.pk])).status_code, 403)
        self.assertTrue(Record.all_companies.filter(pk=record.pk).exists())

    def test_delete_removes_row_and_file(self):
        self.client.force_login(self.owner)
        self.add()
        record = Record.all_companies.get()
        path = record.file.path
        self.client.post(reverse('library:delete', args=[record.pk]))
        self.assertFalse(Record.all_companies.exists())
        import os
        self.assertFalse(os.path.exists(path))

    def test_expiry_before_issue_is_refused(self):
        self.client.force_login(self.owner)
        self.add(issue_date='2026-05-01', expiry_date='2026-04-01')
        self.assertFalse(Record.all_companies.exists())

    def test_expiring_filter_and_badge(self):
        today = timezone.localdate()
        for title, days in (('soon', 10), ('later', 200)):
            Record.all_companies.create(company=self.company, title=title, content_type='application/pdf',
                                        file='1/x.pdf', expiry_date=today + datetime.timedelta(days=days))
        self.client.force_login(self.owner)
        page = self.client.get(reverse('library:list') + '?status=soon')
        self.assertEqual([r.title for r in page.context['entries']], ['soon'])
        self.assertEqual(page.context['library_alerts'], 1)


class ReminderTests(TestCase):
    def setUp(self):
        self.company = make_company('A')
        self.owner = make_user('o@example.com', self.company)
        self.today = timezone.localdate()

    def record(self, days):
        return Record.all_companies.create(company=self.company, title='Licence', content_type='application/pdf',
                                           file='1/x.pdf', expiry_date=self.today + datetime.timedelta(days=days))

    def test_stage_is_sent_once_then_the_next_stage(self):
        record = self.record(25)                           # inside the 30-day stage
        self.assertEqual(reminders.send_due(self.today), 1)
        self.assertEqual(reminders.send_due(self.today), 0)
        self.assertEqual(Notification.objects.filter(user=self.owner, kind='expiring').count(), 1)
        self.assertEqual(len(mail.outbox), 1)
        later = self.today + datetime.timedelta(days=20)    # 5 days left: the 7-day stage
        self.assertEqual(reminders.send_due(later), 1)
        record.refresh_from_db()
        self.assertEqual(record.reminded_days, 7)

    def test_far_expiry_is_not_due(self):
        self.record(200)
        self.assertEqual(reminders.send_due(self.today), 0)

    def test_expired_uses_the_expired_kind(self):
        self.record(-3)
        reminders.send_due(self.today)
        self.assertTrue(Notification.objects.filter(kind='expired').exists())


# --- «Read it for me»: a paid job. The price shown is the price charged (owner's rule 2026-11-18). ---
from unittest import mock

from django.test import override_settings

from apps.ai import client as ai
from apps.credits import catalog, quote as quotes
from apps.credits.models import Wallet
from apps.jobs.models import Job
from apps.jobs.runner import run_job

from . import extract

READ = {'category': 'company', 'title': 'Commercial Registration', 'doc_type': 'Commercial Registration', 'issuer': 'MOCI',
        'reference': 'CR-1', 'issue_date': '2026-01-01', 'expiry_date': '2027-01-01', 'summary': 'A registration.'}


class ReadItForMeTests(TestCase):
    def setUp(self):
        self.company = make_company('A')
        self.owner = make_user('o@example.com', self.company)
        self.client.force_login(self.owner)
        self.shown = quotes.make(extract.SERVICE).total
        self.balance = Wallet.objects.get(company=self.company).balance

    def balance_now(self):
        return Wallet.objects.get(company=self.company).balance

    def upload(self, shown=None, **extra):
        data = {'category': 'company', 'file': upload('scan.pdf'), 'read': 'on',
                'expected_points': self.shown if shown is None else shown}
        data.update(extra)
        return self.client.post(reverse('library:upload'), data)

    def test_form_shows_the_price_that_is_charged(self):
        page = self.client.get(reverse('library:upload'))
        self.assertContains(page, f'name="expected_points" value="{self.shown}"')
        self.assertContains(page, catalog.money(self.shown))
        self.upload()
        self.assertEqual(self.balance - self.balance_now(), self.shown)          # exactly what was shown
        job = Job.objects.get()
        self.assertEqual((job.kind, job.params['service'], job.charge_txn.delta), ('call', 'extract_document', -self.shown))
        self.assertEqual(job.charge_txn.breakdown, [{'key': 'base', 'count': None, 'points': self.shown}])   # the itemised price is kept

    def test_a_changed_price_refuses_without_charging_and_keeps_the_file(self):
        self.upload(shown=self.shown - 1)
        self.assertEqual(self.balance_now(), self.balance)
        self.assertFalse(Job.objects.exists())
        self.assertTrue(Record.all_companies.exists())

    def test_not_enough_balance_keeps_the_file_unread(self):
        Wallet.objects.filter(company=self.company).update(balance=0)
        self.upload()
        self.assertFalse(Job.objects.exists())
        self.assertTrue(Record.all_companies.exists())

    def test_without_reading_nothing_is_charged(self):
        self.client.post(reverse('library:upload'), {'title': 'x', 'category': 'company', 'file': upload()})
        self.assertEqual(self.balance_now(), self.balance)
        self.assertFalse(Job.objects.exists())

    def run_job(self, result=None, error=None):
        job = Job.objects.get()
        patch = mock.patch('apps.library.extract.client.call_json',
                           side_effect=error) if error else mock.patch('apps.library.extract.client.call_json',
                                                                       return_value=ai.AIResult(result, 100, 50, 0, 'claude-opus-5-5'))
        with patch as call:
            run_job(job)
        job.refresh_from_db()
        return job, call

    def test_the_job_fills_the_details_and_names_the_record_after_the_document(self):
        self.upload()
        job, call = self.run_job(READ)
        record = Record.all_companies.get()
        self.assertEqual(job.status, Job.Status.DONE)
        self.assertEqual((record.title, record.doc_type, record.issuer, str(record.expiry_date)),
                         ('Commercial Registration', 'Commercial Registration', 'MOCI', '2027-01-01'))
        self.assertEqual(call.call_args.kwargs['tier'], 'premium')
        self.assertEqual(call.call_args.args[1][0]['type'], 'document')            # the PDF itself is sent
        self.assertEqual(self.balance - self.balance_now(), self.shown)            # charged once, at the quote

    def test_the_members_own_values_are_kept(self):
        self.upload(title='My name', issuer='Mine')
        self.run_job(READ)
        record = Record.all_companies.get()
        self.assertEqual((record.title, record.issuer, record.doc_type), ('My name', 'Mine', 'Commercial Registration'))

    def test_a_failed_read_gives_the_charge_back_and_keeps_the_file(self):
        self.upload()
        job, _call = self.run_job(error=ai.AIError('failed'))
        self.assertEqual(job.status, Job.Status.FAILED)
        self.assertEqual(self.balance_now(), self.balance)
        self.assertTrue(Record.all_companies.exists())

    def test_an_expiry_found_restarts_the_reminders(self):
        self.upload()
        Record.all_companies.update(reminded_days=7)
        self.run_job(READ)
        self.assertIsNone(Record.all_companies.get().reminded_days)

    def test_read_again_button_is_priced_the_same(self):
        self.client.post(reverse('library:upload'), {'title': 'x', 'category': 'company', 'file': upload()})
        record = Record.all_companies.get()
        self.client.post(reverse('library:read', args=[record.pk]), {'expected_points': self.shown})
        self.assertEqual(self.balance - self.balance_now(), self.shown)
        page = self.client.get(reverse('library:list'))
        self.assertTrue(page.context['reading'])
        self.assertContains(page, 'id="readingBanner"')


class VisionRoutingTests(TestCase):
    PDF_BLOCKS = [{'type': 'document', 'source': {}}, {'type': 'text', 'text': 'x'}]

    def test_blocks_with_an_image_or_a_pdf_are_vision(self):
        self.assertTrue(ai.is_vision(self.PDF_BLOCKS))
        self.assertFalse(ai.is_vision('text'))
        self.assertFalse(ai.is_vision([{'type': 'text', 'text': 'x'}]))

    @override_settings(ANTHROPIC_API_KEY='k', DEEPSEEK_API_KEY='d',
                       AI_TIERS={'interactive': ['deepseek', 'deepseek-v4-pro']})
    def test_a_deepseek_tier_is_moved_to_claude_for_vision(self):
        self.assertEqual(ai.resolve('interactive')[0], 'deepseek')
        self.assertEqual(ai.resolve('interactive', vision=True)[0], 'anthropic')

    @override_settings(ANTHROPIC_API_KEY='', DEEPSEEK_API_KEY='d', AI_TIERS={'interactive': ['deepseek', 'deepseek-v4-pro']})
    def test_vision_without_a_claude_key_is_refused(self):
        with self.assertRaises(ai.AIError):
            ai.resolve('interactive', vision=True)
