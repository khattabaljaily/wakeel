"""The console pages moved from MyDocHub: users, wallet ledger, prices, activity, operator change, hard delete."""
from django.test import TestCase
from django.urls import reverse

from apps.accounts.models import User
from apps.audit.models import AuditEvent
from apps.companies.models import Company, Membership
from apps.content.tests import make_company, make_user
from apps.credits import charging
from apps.credits.models import WalletTransaction
from apps.notifications.models import Notification


class ConsoleBase(TestCase):
    def setUp(self):
        self.company = make_company('شركة تجريبية')
        self.owner = make_user('owner@x.test', self.company)
        self.admin = make_user('root@x.test')
        self.admin.is_superuser = self.admin.is_staff = True
        self.admin.set_password('Pass-word-77')
        self.admin.save()
        self.client.force_login(self.admin)


class PagesTests(ConsoleBase):
    def test_hidden_from_non_superusers(self):
        self.client.force_login(self.owner)
        for name in ('users', 'ledger', 'prices', 'activity'):
            self.assertEqual(self.client.get(reverse(f'ops:{name}')).status_code, 404, name)

    def test_pages_render_and_search(self):
        charging.add_points(self.company, 5000, action=WalletTransaction.ADMIN_GRANT, user=self.admin, description='zz-note')
        for name in ('users', 'ledger', 'prices', 'activity'):
            self.assertEqual(self.client.get(reverse(f'ops:{name}')).status_code, 200, name)
        self.assertContains(self.client.get(reverse('ops:users'), {'q': 'owner@'}), 'owner@x.test')
        self.assertNotContains(self.client.get(reverse('ops:users'), {'q': 'nobody'}), 'owner@x.test')
        page = self.client.get(reverse('ops:ledger'), {'action': 'admin_grant'})
        self.assertContains(page, 'zz-note')
        self.assertNotContains(self.client.get(reverse('ops:ledger'), {'action': 'refund'}), 'zz-note')

    def test_activity_lists_every_company(self):
        AuditEvent.all_companies.create(company=self.company, user_email='owner@x.test', action='RECORD_OPEN', target='x')
        self.assertContains(self.client.get(reverse('ops:activity')), 'RECORD_OPEN')

    def test_the_budget_shows_on_the_usage_page(self):
        with self.settings(AI_MONTHLY_BUDGET_USD=50):
            self.assertContains(self.client.get(reverse('ops:usage')), '/ $50')


class UserActionTests(ConsoleBase):
    def test_deactivate_and_reactivate(self):
        self.client.post(reverse('ops:user_active', args=[self.owner.pk]))
        self.owner.refresh_from_db()
        self.assertFalse(self.owner.is_active)
        self.client.post(reverse('ops:user_active', args=[self.owner.pk]))
        self.owner.refresh_from_db()
        self.assertTrue(self.owner.is_active)

    def test_you_cannot_deactivate_yourself(self):
        self.client.post(reverse('ops:user_active', args=[self.admin.pk]))
        self.admin.refresh_from_db()
        self.assertTrue(self.admin.is_active)

    def test_delete_needs_the_password_and_takes_owned_companies_with_it(self):
        url = reverse('ops:user_delete', args=[self.owner.pk])
        self.client.post(url, {'password': 'wrong'})
        self.assertTrue(User.objects.filter(pk=self.owner.pk).exists())
        self.client.post(url, {'password': 'Pass-word-77'})
        self.assertFalse(User.objects.filter(pk=self.owner.pk).exists())
        self.assertFalse(Company.objects.filter(pk=self.company.pk).exists())

    def test_the_last_superuser_is_never_deleted(self):
        self.client.post(reverse('ops:user_delete', args=[self.admin.pk]), {'password': 'Pass-word-77'})
        self.assertTrue(User.objects.filter(pk=self.admin.pk).exists())

    def test_wrong_passwords_are_limited(self):
        url = reverse('ops:user_delete', args=[self.owner.pk])
        for _ in range(5):
            self.client.post(url, {'password': 'wrong'})
        self.client.post(url, {'password': 'Pass-word-77'})          # right, but the pause is on
        self.assertTrue(User.objects.filter(pk=self.owner.pk).exists())


class OperatorChangeTests(ConsoleBase):
    def url(self):
        return reverse('ops:company_operator', args=[self.company.pk])

    def test_only_a_registered_active_operator_is_accepted(self):
        self.company.operator = 'jovia'
        self.company.save(update_fields=['operator'])
        self.client.post(self.url(), {'operator': 'nope'})
        self.client.post(self.url(), {'operator': 'enjaz'})        # registered, but not active for Wakeel yet
        self.company.refresh_from_db()
        self.assertEqual(self.company.operator, 'jovia')
        self.assertContains(self.client.get(reverse('ops:company', args=[self.company.pk])), 'operatorSelect')

    def test_moving_a_company_tells_its_owner(self):
        from unittest import mock
        from apps.companies import operators
        from enjaz_operators import registry
        both = [registry.get(operators.PRODUCT, 'jovia'), registry.get(operators.PRODUCT, 'enjaz')]
        with mock.patch.object(registry, 'operators', return_value=both):
            self.client.post(self.url(), {'operator': 'enjaz'})
        self.company.refresh_from_db()
        self.assertEqual(self.company.operator, 'enjaz')
        self.assertTrue(Notification.objects.filter(user=self.owner, kind='operator_changed').exists())
