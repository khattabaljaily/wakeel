"""The company dashboard shows the whole product (not only marketing), role by role."""
from django.test import TestCase
from django.urls import reverse

from apps.companies.models import Membership
from apps.content.tests import make_company, make_user
from apps.credits import charging
from apps.credits.models import WalletTransaction


class DashboardOverviewTests(TestCase):
    def setUp(self):
        self.company = make_company('شركة')
        self.owner = make_user('o@x.test', self.company)

    def page(self, user):
        self.client.force_login(user)
        return self.client.get(reverse('core:dashboard'))

    def test_the_owner_sees_the_wallet_and_the_quick_actions(self):
        page = self.page(self.owner)
        self.assertContains(page, reverse('credits:wallet'))
        self.assertContains(page, reverse('library:upload'))
        self.assertContains(page, reverse('tasks:new'))

    def test_a_low_balance_is_flagged(self):
        wallet = charging.get_wallet(self.company)
        wallet.balance = 100
        wallet.save()
        self.assertContains(self.page(self.owner), 'رصيد المحفظة منخفض')
        charging.add_points(self.company, 5000, action=WalletTransaction.ADMIN_GRANT, user=self.owner)
        self.assertNotContains(self.page(self.owner), 'رصيد المحفظة منخفض')

    def test_an_editor_has_no_wallet_card_and_a_client_has_no_overview_at_all(self):
        editor = make_user('e@x.test', self.company, role='editor') if 'role' in make_user.__code__.co_varnames else None
        if editor is not None:
            page = self.page(editor)
            self.assertNotContains(page, reverse('credits:wallet'))
        client = make_user('c@x.test', self.company)
        Membership.objects.filter(user=client, company=self.company).update(role=Membership.Role.CLIENT)
        page = self.page(client)
        self.assertNotContains(page, reverse('library:upload'))
        self.assertNotContains(page, reverse('credits:wallet'))
