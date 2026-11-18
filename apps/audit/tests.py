from django.test import RequestFactory, TestCase, override_settings
from django.urls import reverse

from apps.accounts.models import User
from apps.companies.models import Company, Membership
from apps.core.tenancy import company_context

from . import log
from .models import AuditEvent


class Base(TestCase):
    def setUp(self):
        self.company = Company.objects.create(name='Alpha', industry='x', country='Qatar')
        self.owner = self.member('owner@example.com', 'owner')
        self.admin = self.member('admin@example.com', 'admin')
        self.editor = self.member('editor@example.com', 'editor')
        self.viewer = self.member('viewer@example.com', 'viewer')
        self.client.force_login(self.owner)

    def member(self, email, role, company=None):
        user = User.objects.create_user(email, email, 'a-Strong-pass-77')
        Membership.objects.create(company=company or self.company, user=user, role=role)
        return user

    def events(self, action=None):
        rows = AuditEvent.all_companies.filter(company=self.company)
        return rows.filter(action=action) if action else rows


class AuditLogTests(Base):
    def test_an_event_is_never_changed_or_deleted(self):
        event = AuditEvent.all_companies.create(company=self.company, action='x', target='t')
        event.target = 'changed'
        with self.assertRaises(PermissionError):
            event.save()
        with self.assertRaises(PermissionError):
            event.delete()
        self.assertEqual(AuditEvent.all_companies.get(pk=event.pk).target, 't')

    def test_record_keeps_who_and_from_where_and_never_raises(self):
        request = RequestFactory().get('/', REMOTE_ADDR='203.0.113.9')
        request.user, request.company = self.owner, self.company
        log.record(request, 'document.opened', 'Letter', replaced=True)
        event = self.events().get()
        self.assertEqual((event.user_email, event.ip, event.detail), ('owner@example.com', '203.0.113.9', {'replaced': True}))
        request.company = None
        log.record(request, 'document.opened', 'Letter')            # no company: logged as an error, not raised
        self.assertEqual(self.events().count(), 1)

    def test_a_forged_forwarding_header_is_not_trusted_without_a_proxy(self):
        request = RequestFactory().get('/', REMOTE_ADDR='198.51.100.1', HTTP_X_FORWARDED_FOR='1.2.3.4')
        self.assertEqual(log.client_ip(request), '198.51.100.1')
        with override_settings(USE_X_FORWARDED_HOST=True):
            self.assertEqual(log.client_ip(request), '1.2.3.4')

    def test_only_owners_and_admins_read_the_log_and_only_their_own_company(self):
        AuditEvent.all_companies.create(company=self.company, action='document.opened', target='Letter', user_email='o@example.com')
        beta = Company.objects.create(name='Beta', industry='x', country='Qatar')
        AuditEvent.all_companies.create(company=beta, action='document.opened', target='beta-letter')
        url = reverse('audit:activity')
        for user, status in ((self.owner, 200), (self.admin, 200), (self.editor, 403), (self.viewer, 403)):
            self.client.force_login(user)
            self.assertEqual(self.client.get(url).status_code, status, user.email)
        self.client.force_login(self.owner)
        self.client.cookies['wakeel_lang'] = 'en'
        page = self.client.get(url).content.decode()
        self.assertIn('Opened the text of a document', page)
        self.assertNotIn('beta-letter', page)
        self.client.logout()
        self.assertEqual(self.client.get(url).status_code, 302)
