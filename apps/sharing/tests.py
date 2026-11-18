import datetime
from unittest import mock

from django.core.cache import cache
from django.core.files.base import ContentFile
from django.test import Client, TestCase
from django.urls import reverse
from django.utils import timezone

from apps.audit.models import AuditEvent
from apps.companies.models import Membership
from apps.content.tests import make_company, make_user
from apps.documents.models import Document
from apps.library.models import Record
from apps.library.tests import PDF

from .models import ShareAccess, ShareLink


class Base(TestCase):
    def setUp(self):
        cache.clear()
        self.company = make_company('Alpha')
        self.other = make_company('Beta')
        self.owner = make_user('o@example.com', self.company)
        self.editor = make_user('m@example.com', self.company, Membership.Role.EDITOR)
        self.stranger = make_user('s@example.com', self.other)
        self.client.force_login(self.owner)
        self.record = Record(company=self.company, title='Trade licence', content_type='application/pdf')
        self.record.file.save('x.pdf', ContentFile(PDF), save=False)
        self.record.save()

    def document(self, **fields):
        doc = Document(company=self.company, title='Letter', language='en', created_by=self.owner, **fields)
        doc.subject, doc.body = 'S', 'Text'
        doc.save()
        return doc

    def link(self, **fields):
        return ShareLink.make(fields.pop('target', self.record), self.owner, fields.pop('days', 7), **fields)

    def visitor(self):
        return Client()

    def url(self, link, *more):
        return reverse('shared:open', args=[link.token]) + ''.join(more)


class MakingTests(Base):
    def test_the_owner_makes_a_link_and_it_is_logged(self):
        url = reverse('sharing:new', args=['record', self.record.pk])
        self.assertEqual(self.client.get(url).status_code, 200)
        response = self.client.post(url, {'days': '7', 'password': 'secret1', 'allow_download': 'on'})
        link = ShareLink.all_companies.get()
        self.assertRedirects(response, f"{reverse('sharing:list')}?new={link.pk}")
        self.assertTrue(link.has_password and link.allow_download)
        self.assertNotIn('secret1', link.password_hash)                         # only the hash is kept
        self.assertTrue(AuditEvent.all_companies.filter(company=self.company, action=AuditEvent.SHARE_CREATED).exists())
        self.assertContains(self.client.get(response['Location']), link.token)

    def test_bad_input_makes_nothing(self):
        url = reverse('sharing:new', args=['record', self.record.pk])
        self.client.post(url, {'days': '5'})
        self.client.post(url, {'days': '7', 'password': '123'})
        self.assertFalse(ShareLink.all_companies.exists())

    def test_only_managers_share_and_only_their_own_company(self):
        url = reverse('sharing:new', args=['record', self.record.pk])
        self.client.force_login(self.editor)
        self.assertEqual(self.client.get(url).status_code, 403)
        self.assertEqual(self.client.get(reverse('sharing:list')).status_code, 403)
        self.client.force_login(self.stranger)
        self.assertEqual(self.client.get(url).status_code, 404)
        self.assertEqual(self.client.post(url, {'days': '7'}).status_code, 404)
        self.assertFalse(ShareLink.all_companies.exists())

    def test_a_document_must_be_approved_and_valid_to_be_shared(self):
        for fields in ({'status': Document.PENDING}, {'status': Document.REJECTED}, {'revoked_at': timezone.now()}):
            doc = self.document(**fields)
            self.client.post(reverse('sharing:new', args=['document', doc.pk]), {'days': '7'})
        self.assertFalse(ShareLink.all_companies.exists())
        ok = self.document()
        self.client.post(reverse('sharing:new', args=['document', ok.pk]), {'days': '7'})
        self.assertEqual(ShareLink.all_companies.count(), 1)

    def test_revoking_is_for_managers_and_logged(self):
        link = self.link()
        self.client.force_login(self.editor)
        self.client.post(reverse('sharing:revoke', args=[link.pk]))
        link.refresh_from_db()
        self.assertIsNone(link.revoked_at)
        self.client.force_login(self.owner)
        self.client.post(reverse('sharing:revoke', args=[link.pk]))
        link.refresh_from_db()
        self.assertEqual(link.status, 'revoked')
        self.assertTrue(AuditEvent.all_companies.filter(company=self.company, action=AuditEvent.SHARE_REVOKED).exists())

    def test_another_company_cannot_see_or_cancel_a_link(self):
        link = self.link()
        self.client.force_login(self.stranger)
        self.assertEqual(self.client.get(reverse('sharing:detail', args=[link.pk])).status_code, 404)
        self.assertEqual(self.client.post(reverse('sharing:revoke', args=[link.pk])).status_code, 404)


class VisitorTests(Base):
    def test_a_visitor_needs_no_account_and_the_visit_is_written_down(self):
        link = self.link()
        visitor = self.visitor()
        page = visitor.get(self.url(link))
        self.assertContains(page, 'Trade licence')
        self.assertContains(page, 'Alpha')
        self.assertEqual(page['X-Robots-Tag'], 'noindex, nofollow')
        self.assertEqual(page['Cache-Control'], 'no-store')
        access = ShareAccess.all_companies.get()
        self.assertEqual((access.action, access.link), (ShareAccess.VIEW, link))
        file = visitor.get(self.url(link, 'file/'))
        self.assertEqual(file.status_code, 200)
        self.assertEqual(b''.join(file.streaming_content)[:5], b'%PDF-')

    def test_an_expired_cancelled_or_unknown_link_all_answer_the_same(self):
        expired = self.link()
        ShareLink.all_companies.filter(pk=expired.pk).update(expires_at=timezone.now() - datetime.timedelta(minutes=1))
        revoked = self.link()
        ShareLink.all_companies.filter(pk=revoked.pk).update(revoked_at=timezone.now())
        for target in (self.url(expired), self.url(revoked), reverse('shared:open', args=['x' * 32])):
            response = self.visitor().get(target)
            self.assertEqual(response.status_code, 404, target)
        self.assertEqual(ShareAccess.all_companies.count(), 0)

    def test_a_password_link_locks_until_the_right_password_and_counts_wrong_tries(self):
        link = self.link(password='secret1')
        visitor = self.visitor()
        self.assertEqual(visitor.get(self.url(link)).status_code, 200)               # the lock page
        self.assertEqual(visitor.get(self.url(link, 'file/')).status_code, 404)      # the file stays closed
        wrong = visitor.post(self.url(link), {'password': 'nope'})
        self.assertEqual(wrong.status_code, 401)
        self.assertEqual(ShareAccess.all_companies.filter(action=ShareAccess.WRONG_PASSWORD).count(), 1)
        self.assertNotContains(wrong, '<iframe', status_code=401)
        right = visitor.post(self.url(link), {'password': 'secret1'})
        self.assertContains(right, '<iframe')
        self.assertEqual(visitor.get(self.url(link, 'file/')).status_code, 200)

    def test_too_many_wrong_passwords_block_even_the_right_one(self):
        link = self.link(password='secret1')
        visitor = self.visitor()
        for _i in range(5):
            visitor.post(self.url(link), {'password': 'bad'})
        self.assertEqual(visitor.post(self.url(link), {'password': 'secret1'}).status_code, 429)

    def test_saving_a_copy_only_when_allowed_and_logged(self):
        closed, opened = self.link(), self.link(allow_download=True)
        self.assertEqual(self.visitor().get(self.url(closed, 'file/?download=1')).status_code, 403)
        response = self.visitor().get(self.url(opened, 'file/?download=1'))
        self.assertIn('attachment', response['Content-Disposition'])
        self.assertTrue(ShareAccess.all_companies.filter(link=opened, action=ShareAccess.DOWNLOAD).exists())
        self.assertFalse(ShareAccess.all_companies.filter(link=closed, action=ShareAccess.DOWNLOAD).exists())

    def test_a_document_link_shows_the_pdf_and_dies_when_the_document_is_cancelled(self):
        doc = self.document()
        link = self.link(target=doc)
        visitor = self.visitor()
        with mock.patch('apps.documents.pdf.available', return_value=True), \
                mock.patch('apps.documents.pdf.html_to_pdf', return_value=b'%PDF-1.4 fake'):
            response = visitor.get(self.url(link, 'file/'))
        self.assertEqual((response.status_code, response.content), (200, b'%PDF-1.4 fake'))
        Document.all_companies.filter(pk=doc.pk).update(revoked_at=timezone.now())
        self.assertEqual(visitor.get(self.url(link)).status_code, 404)

    def test_the_log_page_lists_who_opened_it_for_managers_only(self):
        link = self.link()
        self.visitor().get(self.url(link))
        page = self.client.get(reverse('sharing:detail', args=[link.pk]))
        self.assertContains(page, '127.0.0.1')
        self.assertContains(self.client.get(reverse('sharing:list')), 'Trade licence')
