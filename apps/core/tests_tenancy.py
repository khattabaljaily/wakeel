from django.test import TestCase
from django.urls import reverse

from apps.accounts.models import User
from apps.companies.models import Company, Membership
from apps.core.tenancy import CompanyRequired, company_context, get_current_company
from apps.core.testapp.models import Note


def make_company(name):
    return Company.objects.create(name=name, industry='x', country='Qatar')


class CompanyTestCase(TestCase):
    @classmethod
    def setUpTestData(cls):
        cls.a = make_company('Alpha')
        cls.b = make_company('Beta')
        cls.alice = User.objects.create_user('alice', 'alice@example.com', 'pw-alice-123')
        cls.bob = User.objects.create_user('bob', 'bob@example.com', 'pw-bob-12345')
        Membership.objects.create(company=cls.a, user=cls.alice, role='owner')
        Membership.objects.create(company=cls.b, user=cls.bob, role='owner')
        with company_context(cls.a):
            Note.objects.create(title='alpha note')
        with company_context(cls.b):
            Note.objects.create(title='beta note')


class IsolationTests(CompanyTestCase):
    def test_query_without_company_is_refused(self):
        with self.assertRaises(CompanyRequired):
            list(Note.objects.all())
        with self.assertRaises(CompanyRequired):
            Note.objects.count()
        with self.assertRaises(CompanyRequired):
            Note.objects.get(title='alpha note')

    def test_save_without_company_is_refused(self):
        with self.assertRaises(CompanyRequired):
            Note.objects.create(title='orphan')

    def test_queries_only_see_the_active_company(self):
        with company_context(self.a):
            self.assertEqual([n.title for n in Note.objects.all()], ['alpha note'])
        with company_context(self.b):
            self.assertEqual([n.title for n in Note.objects.all()], ['beta note'])

    def test_other_companys_row_cannot_be_fetched_by_pk(self):
        beta_id = Note.all_companies.get(title='beta note').pk
        with company_context(self.a):
            self.assertFalse(Note.objects.filter(pk=beta_id).exists())
            with self.assertRaises(Note.DoesNotExist):
                Note.objects.get(pk=beta_id)

    def test_new_rows_get_the_active_company(self):
        with company_context(self.a):
            note = Note.objects.create(title='another')
        self.assertEqual(note.company, self.a)

    def test_for_company_is_explicit(self):
        self.assertEqual(Note.objects.for_company(self.b).get().title, 'beta note')

    def test_context_is_restored(self):
        with company_context(self.a):
            with company_context(self.b):
                self.assertEqual(get_current_company(), self.b)
            self.assertEqual(get_current_company(), self.a)
        self.assertIsNone(get_current_company())


class MiddlewareTests(CompanyTestCase):
    def test_request_gets_the_users_company_and_context_is_reset(self):
        self.client.force_login(self.alice)
        response = self.client.get(reverse('core:dashboard'))
        self.assertEqual(response.wsgi_request.company, self.a)
        self.assertIsNone(get_current_company())

    def test_session_cannot_select_a_foreign_company(self):
        self.client.force_login(self.alice)
        session = self.client.session
        session['wakeel_company_id'] = self.b.pk  # alice is not a member of beta
        session.save()
        response = self.client.get(reverse('core:dashboard'))
        self.assertEqual(response.wsgi_request.company, self.a)

    def test_the_context_is_set_while_the_view_runs(self):
        seen = {}
        from apps.companies import middleware

        def view(request):
            seen['company'] = get_current_company()
            from django.http import HttpResponse
            return HttpResponse('ok')

        self.client.force_login(self.alice)
        request = self.client.get(reverse('core:dashboard')).wsgi_request
        request.company = None
        mw = middleware.CurrentCompanyMiddleware(view)
        mw(request)
        self.assertEqual(seen['company'], self.a)
