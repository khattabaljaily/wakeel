"""Contacts: the company's address book and each contact's history; who may do what; isolation between companies."""
from django.conf import settings
from django.test import TestCase
from django.urls import reverse

from apps.audit.models import AuditEvent
from apps.companies.models import Membership
from apps.content.tests import make_company, make_user

from .models import Contact, Interaction


class Base(TestCase):
    def setUp(self):
        self.company = make_company('Alpha')
        self.other = make_company('Beta')
        self.owner = make_user('owner@example.com', self.company)
        self.member = make_user('member@example.com', self.company, Membership.Role.EDITOR)
        self.viewer = make_user('viewer@example.com', self.company, Membership.Role.VIEWER)
        self.client.cookies[settings.LANGUAGE_COOKIE_NAME] = 'en'
        self.client.force_login(self.owner)

    def contact(self, **kw):
        return Contact.all_companies.create(company=self.company, name=kw.pop('name', 'Nour Trading'), **kw)

    def contacts(self):
        return Contact.all_companies.filter(company=self.company)


class Book(Base):
    def test_add_find_and_log(self):
        r = self.client.post(reverse('contacts:new'), {'kind': 'supplier', 'name': 'Nour Trading', 'organization': 'Nour LLC',
                                                       'email': 'nour@example.com', 'phone': '+249 91 000 0000'})
        c = self.contacts().get()
        self.assertRedirects(r, reverse('contacts:detail', args=[c.pk]))
        self.assertEqual((c.kind, c.created_by, c.company, c.organization), ('supplier', self.owner, self.company, 'Nour LLC'))
        self.client.post(reverse('contacts:log', args=[c.pk]), {'kind': 'call', 'date': '2030-01-02', 'body': 'Agreed on the price'})
        self.assertEqual((Interaction.all_companies.get().author, Interaction.all_companies.get().company), (self.owner, self.company))
        self.assertContains(self.client.get(reverse('contacts:detail', args=[c.pk])), 'Agreed on the price')
        self.assertEqual(len(self.client.get(reverse('contacts:list'), {'q': 'nour llc'}).context['contacts']), 1)
        self.assertEqual(len(self.client.get(reverse('contacts:list'), {'kind': 'client'}).context['contacts']), 0)
        self.assertEqual(AuditEvent.all_companies.filter(company=self.company, action='contact.created').count(), 1)

    def test_empty_log_line_is_refused(self):
        c = self.contact()
        self.client.post(reverse('contacts:log', args=[c.pk]), {'kind': 'note', 'date': '2030-01-02', 'body': ' '})
        self.assertFalse(Interaction.all_companies.exists())

    def test_the_chosen_filter_is_the_default_type_and_a_refused_form_opens_again(self):
        page = self.client.get(reverse('contacts:list'), {'kind': 'supplier'})
        self.assertEqual(page.context['form'].initial['kind'], 'supplier')
        page = self.client.post(reverse('contacts:new'), {'name': '', 'kind': 'client'})
        self.assertContains(page, 'collapse show')
        self.assertTrue(page.context['form'].errors)


class Permissions(Base):
    def test_viewer_reads_but_cannot_write(self):
        c = self.contact()
        self.client.force_login(self.viewer)
        self.assertEqual(self.client.get(reverse('contacts:detail', args=[c.pk])).status_code, 200)
        self.assertNotContains(self.client.get(reverse('contacts:list')), 'id="newContact"')
        self.client.post(reverse('contacts:new'), {'name': 'x', 'kind': 'client'})
        self.client.post(reverse('contacts:log', args=[c.pk]), {'body': 'x', 'kind': 'note', 'date': '2030-01-01'})
        self.client.post(reverse('contacts:delete', args=[c.pk]))
        self.assertEqual((self.contacts().count(), Interaction.all_companies.count()), (1, 0))

    def test_an_outside_client_of_the_company_sees_no_contacts(self):
        c = self.contact()
        self.client.force_login(make_user('client@example.com', self.company, Membership.Role.CLIENT))
        self.assertEqual(self.client.get(reverse('contacts:list')).status_code, 403)
        self.assertEqual(self.client.get(reverse('contacts:detail', args=[c.pk])).status_code, 403)

    def test_an_editor_deletes_only_what_they_added(self):
        theirs = self.contact(name='Theirs', created_by=self.member)
        mine = self.contact(name='Owner added', created_by=self.owner)
        self.client.force_login(self.member)
        self.assertEqual(self.client.post(reverse('contacts:delete', args=[mine.pk])).status_code, 403)
        self.client.post(reverse('contacts:delete', args=[theirs.pk]))
        self.assertEqual(list(self.contacts()), [mine])

    def test_only_its_author_or_a_manager_removes_a_history_line(self):
        c = self.contact()
        line = Interaction.all_companies.create(company=self.company, contact=c, body='x', author=self.owner)
        self.client.force_login(self.member)
        self.assertEqual(self.client.post(reverse('contacts:log_delete', args=[line.pk])).status_code, 403)
        self.client.force_login(self.owner)
        self.client.post(reverse('contacts:log_delete', args=[line.pk]))
        self.assertFalse(Interaction.all_companies.exists())

    def test_another_company_sees_nothing(self):
        c = self.contact()
        line = Interaction.all_companies.create(company=self.company, contact=c, body='x', author=self.owner)
        self.client.force_login(make_user('stranger@example.com', self.other))
        self.assertEqual(self.client.get(reverse('contacts:detail', args=[c.pk])).status_code, 404)
        self.assertEqual(self.client.post(reverse('contacts:delete', args=[c.pk])).status_code, 404)
        self.assertEqual(self.client.post(reverse('contacts:log', args=[c.pk]), {'kind': 'note', 'date': '2030-01-01', 'body': 'x'}).status_code, 404)
        self.assertEqual(self.client.post(reverse('contacts:log_delete', args=[line.pk])).status_code, 404)
        self.assertEqual(len(self.client.get(reverse('contacts:list')).context['contacts']), 0)
