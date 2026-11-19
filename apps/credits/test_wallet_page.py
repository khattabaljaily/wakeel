"""The wallet page: balance, month figures, packages, and the ledger filters."""
from django.test import TestCase
from django.urls import reverse

from apps.content.tests import make_company, make_user
from apps.credits import charging
from apps.credits.models import Wallet, WalletTransaction as W


class WalletPageTests(TestCase):
    def setUp(self):
        self.company = make_company('شركة')
        self.owner = make_user('o@x.test', self.company)
        Wallet.objects.filter(company=self.company).update(balance=0)
        charging.add_points(self.company, 5000, action=W.TOPUP, user=self.owner, description='card')
        W.objects.create(company=self.company, delta=-120, action=W.AI_SERVICE, service_key='extract_document', breakdown=[{'key': 'extract_document', 'points': 120}])
        W.objects.create(company=self.company, delta=40, action=W.REFUND, service_key='extract_document')
        self.client.force_login(self.owner)
        self.client.post(reverse('core:set_language'), {'language': 'en'})

    def page(self, **params):
        return self.client.get(reverse('credits:wallet'), params)

    def test_balance_and_month_figures(self):
        page = self.page()
        self.assertContains(page, '$5.00')                       # the balance as the wallet holds it
        self.assertContains(page, 'Added this month')
        self.assertEqual(page.context['month'], {'added': '5.00', 'used': '0.08', 'uses': 1})

    def test_every_package_is_offered_including_the_hundred(self):
        page = self.page()
        for amount in ('10', '25', '50', '100'):
            self.assertContains(page, f'value="{amount}"')

    def test_ledger_filters(self):
        self.assertContains(self.page(type='refund'), 'Refund')
        out = self.page(type='out')
        self.assertContains(out, 'extract_document')
        self.assertNotContains(out, 'card</')
        self.assertEqual(len(self.page(type='in').context['page']), 2)      # the top-up and the refund both add
        self.assertEqual(len(self.page(type='nonsense').context['page']), 3)  # an unknown filter is ignored

    def test_a_low_balance_is_flagged_and_an_exempt_company_is_not(self):
        Wallet.objects.filter(company=self.company).update(balance=100)
        self.assertContains(self.page(), 'The balance is low')
        Wallet.objects.filter(company=self.company).update(is_exempt=True)
        self.assertNotContains(self.page(), 'The balance is low')
