"""The operating model in Wakeel (enjaz-operators): a company is served by the operator of its country."""
from django.test import TestCase
from django.urls import reverse

from apps.accounts.models import User

from . import operators
from .models import Company, Membership


class OperatorTests(TestCase):
    def test_country_written_as_text_becomes_a_code(self):
        for text, code in (('قطر', 'QA'), ('Qatar', 'QA'), ('السودان', 'SD'), ('Sudan', 'SD'), ('qa', 'QA'),
                           ('الإمارات', 'AE'), ('الامارات', 'AE'), ('', ''), ('Atlantis', '')):
            self.assertEqual(operators.code_from_name(text), code, text)

    def test_a_new_company_gets_the_operator_of_its_country(self):
        company = Company.objects.create(name='Doha Co', industry='x', country='قطر')
        self.assertEqual((company.country_code, company.operator), ('QA', 'banan'))
        unknown = Company.objects.create(name='Elsewhere', industry='x', country='Atlantis')
        self.assertEqual((unknown.country_code, unknown.operator), ('', 'banan'))  # the product's default

    def test_a_company_without_an_operator_is_served_by_the_default(self):
        self.assertEqual(operators.of_company(Company(name='Old')).key, 'banan')
        self.assertEqual(operators.of_company(None).key, 'banan')

    def test_the_signed_in_company_sees_its_operator_under_the_page(self):
        company = Company.objects.create(name='Doha Co', industry='x', country='قطر')
        user = User.objects.create_user('o@example.com', 'o@example.com', 'a-Strong-pass-77')
        Membership.objects.create(company=company, user=user, role='owner')
        self.client.force_login(user)
        page = self.client.get(reverse('core:dashboard')).content.decode()
        self.assertIn('wk-credit', page)
        self.assertIn('operators/banan.png', page)
