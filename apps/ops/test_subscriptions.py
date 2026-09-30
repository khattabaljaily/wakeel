import datetime

from django.core import mail
from django.test import TestCase
from django.urls import reverse
from django.utils import timezone

from apps.accounts.models import User
from apps.companies.models import Company, Membership
from apps.content.models import ContentPlan, Post
from apps.content.tests import make_company, make_user
from apps.social.models import SocialAccount
from apps.social.services import due_posts


def superuser(email='root@x.test'):
    user = make_user(email)
    user.is_superuser = user.is_staff = True
    user.save()
    return user


class SignupApprovalTests(TestCase):
    """Sign-up -> awaiting approval -> approved, as in enjazpms."""

    def setUp(self):
        self.admin = superuser()
        self.client.post(reverse('accounts:register'), {
            'first_name': 'سارة', 'email': 's@x.test', 'password': 'Strong-pass-123',
            'company_name': 'مطعم النيل', 'industry': 'مطاعم', 'country': 'السودان', 'phone': '+249 912 000 111'})
        self.company = Company.objects.get(name='مطعم النيل')
        self.owner = User.objects.get(email='s@x.test')

    def test_new_company_waits_and_admins_are_told(self):
        self.assertEqual(self.company.subscription_status, 'pending')
        self.assertEqual([m.to for m in mail.outbox], [['root@x.test']])
        self.assertIn('مطعم النيل', mail.outbox[0].subject)
        # Every app page and the API lead to the status page / are refused.
        for name in ('core:dashboard', 'content:plan_list', 'companies:brand', 'social:accounts'):
            self.assertRedirects(self.client.get(reverse(name)), reverse('companies:status'))
        self.assertContains(self.client.get(reverse('companies:status')), 'حسابك قيد المراجعة')
        post = Post.objects.create(company=self.company, title='م', platforms=['facebook'])
        self.assertEqual(self.client.get(reverse('api:post_detail', args=[post.pk])).status_code, 403)

    def test_admin_approves_as_trial_for_14_days(self):
        mail.outbox.clear()
        self.client.force_login(self.admin)
        self.client.post(reverse('ops:subscription_approve', args=[self.company.pk]), {'is_demo': '1', 'days': '14'})
        self.company.refresh_from_db()
        self.assertEqual(self.company.subscription_status, 'active')
        self.assertTrue(self.company.is_demo)
        self.assertEqual(self.company.subscription_expires, timezone.localdate() + datetime.timedelta(days=14))
        self.assertIsNotNone(self.company.approved_at)
        self.assertEqual([m.to for m in mail.outbox], [['s@x.test']])  # the owner hears it's live
        self.client.force_login(self.owner)
        self.assertEqual(self.client.get(reverse('core:dashboard')).status_code, 200)

    def test_pending_tab_and_sidebar_badge(self):
        self.client.force_login(self.admin)
        response = self.client.get(reverse('ops:subscriptions'), {'status': 'pending'})
        self.assertEqual([r['company'] for r in response.context['page']], [self.company])
        self.assertEqual(response.context['stats']['pending'], 1)
        self.assertContains(response, 'wk-nav__badge--gold')


class SubscriptionActionTests(TestCase):
    def setUp(self):
        self.admin = superuser()
        self.company = make_company('إنجاز')
        self.owner = make_user('owner@x.test', self.company)
        self.client.force_login(self.admin)

    def post(self, name, data=None):
        return self.client.post(reverse(f'ops:{name}', args=[self.company.pk]), data or {})

    def test_suspend_blocks_the_team_publishing_and_client_link(self):
        plan = ContentPlan.objects.create(company=self.company, month=datetime.date(2026, 10, 1), platforms=['facebook'],
                                          status='ready', share_token='tok')
        Company.objects.filter(pk=self.company.pk).update(auto_publish=True)
        SocialAccount.objects.create(company=self.company, platform='facebook', external_id='P', name='P', access_token='t')
        Post.objects.create(company=self.company, plan=plan, title='م', platforms=['facebook'], status='approved',
                            scheduled_at=timezone.now() - datetime.timedelta(minutes=5))
        self.assertEqual(due_posts().count(), 1)

        self.post('subscription_toggle')
        self.company.refresh_from_db()
        self.assertEqual(self.company.subscription_status, 'suspended')
        self.assertEqual(due_posts().count(), 0)
        self.assertEqual(self.client.get(reverse('review:plan', args=['tok'])).status_code, 404)
        self.client.force_login(self.owner)
        self.assertRedirects(self.client.get(reverse('core:dashboard')), reverse('companies:status'))
        self.assertContains(self.client.get(reverse('companies:status')), 'معلّق')

        self.client.force_login(self.admin)
        self.post('subscription_toggle')  # reactivate
        self.company.refresh_from_db()
        self.assertTrue(self.company.is_usable)

    def test_expired_subscription_and_renewal(self):
        today = timezone.localdate()
        Company.objects.filter(pk=self.company.pk).update(subscription_expires=today - datetime.timedelta(days=3))
        self.client.force_login(self.owner)
        self.assertRedirects(self.client.get(reverse('core:dashboard')), reverse('companies:status'))
        self.assertContains(self.client.get(reverse('companies:status')), 'انتهى اشتراك')
        self.client.force_login(self.admin)
        response = self.client.get(reverse('ops:subscriptions'), {'status': 'expired'})
        self.assertEqual(len(response.context['page']), 1)

        # Renewing a lapsed subscription counts from today (and a trial can become paid)...
        Company.objects.filter(pk=self.company.pk).update(is_demo=True)
        self.post('subscription_renew', {'days': '30', 'is_demo': '0'})
        self.company.refresh_from_db()
        self.assertEqual(self.company.subscription_expires, today + datetime.timedelta(days=30))
        self.assertFalse(self.company.is_demo)
        # ...and a running one from its current end.
        self.post('subscription_renew', {'days': '30'})
        self.company.refresh_from_db()
        self.assertEqual(self.company.subscription_expires, today + datetime.timedelta(days=60))
        self.assertEqual(self.post('subscription_renew', {'days': '0'}).status_code, 302)
        self.company.refresh_from_db()
        self.assertEqual(self.company.subscription_expires, today + datetime.timedelta(days=60))

    def test_edit(self):
        self.post('subscription_update', {'name': 'إنجاز الجديدة', 'industry': 'تقنية', 'country': 'قطر', 'city': 'الدوحة',
                                          'email': 'info@enjaz.test', 'phone': '+97455', 'timezone': 'Asia/Qatar',
                                          'subscription_start': '2026-01-01', 'subscription_expires': '2027-01-31', 'is_demo': 'on'})
        self.company.refresh_from_db()
        self.assertEqual((self.company.name, self.company.email, self.company.city, self.company.is_demo),
                         ('إنجاز الجديدة', 'info@enjaz.test', 'الدوحة', True))
        self.assertEqual((self.company.subscription_start, self.company.subscription_expires),
                         (datetime.date(2026, 1, 1), datetime.date(2027, 1, 31)))

    def test_edit_rejects_end_before_start(self):
        response = self.post('subscription_update', {'name': 'إنجاز', 'industry': 'ت', 'country': 'قطر', 'timezone': 'Asia/Qatar',
                                                     'subscription_start': '2026-05-01', 'subscription_expires': '2026-04-01'})
        self.assertContains(response, 'قبل بدايته', status_code=400)
        self.assertContains(response, 'data-open', status_code=400)

    def test_delete_needs_the_exact_name(self):
        self.post('subscription_delete', {'confirm_name': 'غلط'})
        self.assertTrue(Company.objects.filter(pk=self.company.pk).exists())
        self.post('subscription_delete', {'confirm_name': 'إنجاز'})
        self.assertFalse(Company.objects.filter(pk=self.company.pk).exists())
        self.assertTrue(User.objects.filter(email='owner@x.test').exists())  # members' accounts stay

    def test_create_with_new_or_existing_owner(self):
        data = {'name': 'بنان', 'industry': 'استشارات', 'country': 'قطر', 'timezone': 'Asia/Qatar', 'description': 'و',
                'email': 'info@banan.test', 'subscription_start': '2026-10-01', 'subscription_expires': '2027-10-01',
                'owner_name': 'أحمد', 'owner_email': 'New@x.test', 'owner_password': 'Strong-pass-123',
                'owner_password2': 'Strong-pass-123'}
        self.assertRedirects(self.client.post(reverse('ops:subscription_create'), data), reverse('ops:subscriptions'))
        company = Company.objects.get(name='بنان')
        self.assertEqual(company.subscription_status, 'active')
        self.assertEqual(company.subscription_expires, datetime.date(2027, 10, 1))
        owner = Membership.objects.get(company=company, role='owner').user
        self.assertEqual(owner.email, 'new@x.test')
        self.assertTrue(owner.check_password('Strong-pass-123'))

        # An existing account becomes the owner, no password needed.
        data.update(name='لمسة', owner_email='owner@x.test', owner_password='', owner_password2='')
        self.client.post(reverse('ops:subscription_create'), data)
        self.assertEqual(Membership.objects.get(company__name='لمسة', role='owner').user, self.owner)

    def test_create_errors_reopen_the_dialog(self):
        base = {'name': 'x', 'industry': 'x', 'country': 'x', 'timezone': 'Asia/Qatar', 'description': 'x',
                'subscription_start': '2026-10-01', 'owner_name': 'x', 'owner_email': 'fresh@x.test'}
        response = self.client.post(reverse('ops:subscription_create'), base)
        self.assertContains(response, 'كلمة المرور مطلوبة', status_code=400)
        self.assertContains(response, 'data-open', status_code=400)
        response = self.client.post(reverse('ops:subscription_create'),
                                    {**base, 'owner_password': 'Strong-pass-123', 'owner_password2': 'Other-pass-456'})
        self.assertContains(response, 'غير متطابقتين', status_code=400)
        self.assertFalse(Company.objects.filter(name='x').exists())

    def test_login_as_owner_and_back(self):
        # The admin's password is asked again.
        self.post('subscription_login_as', {'password': 'wrong'})
        self.assertEqual(int(self.client.session['_auth_user_id']), self.admin.pk)

        response = self.post('subscription_login_as', {'password': 'Pass12345!x'})
        self.assertRedirects(response, reverse('core:dashboard'))
        self.assertEqual(int(self.client.session['_auth_user_id']), self.owner.pk)
        page = self.client.get(reverse('core:dashboard'))
        self.assertContains(page, 'بصفتك مشرف النظام')
        self.assertContains(page, reverse('accounts:exit_impersonation'))

        response = self.client.post(reverse('accounts:exit_impersonation'))
        self.assertRedirects(response, reverse('ops:subscriptions'))
        self.assertEqual(int(self.client.session['_auth_user_id']), self.admin.pk)
        self.assertNotIn('_impersonator_id', self.client.session)

    def test_a_subscriber_cannot_fake_their_way_back_to_admin(self):
        self.client.force_login(self.owner)
        session = self.client.session
        session['_impersonator_id'] = self.owner.pk  # not a superuser
        session.save()
        self.client.post(reverse('accounts:exit_impersonation'))
        self.assertNotIn('_auth_user_id', self.client.session)  # logged out, not promoted

    def test_subscribers_cannot_reach_the_actions(self):
        self.client.force_login(self.owner)
        for name in ('subscription_approve', 'subscription_renew', 'subscription_toggle', 'subscription_delete',
                     'subscription_update', 'subscription_login_as'):
            self.assertEqual(self.post(name).status_code, 404, name)
        self.assertEqual(self.client.post(reverse('ops:subscription_create')).status_code, 404)
