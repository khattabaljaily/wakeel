import datetime
from decimal import Decimal
from unittest import mock

from django.test import SimpleTestCase, TestCase, override_settings
from django.urls import reverse

from apps.accounts.models import User
from apps.companies.models import Company, Membership
from apps.content.models import ContentPlan
from apps.jobs.models import Job
from apps.jobs.runner import run_job

from . import catalog, charging, jobs as credit_jobs, quote as quotes
from .models import Wallet, WalletTransaction
from .pricing import sale_price_usd


def make_company(balance=0, **kwargs):
    company = Company.objects.create(name='Alpha', industry='x', country='Qatar', **kwargs)
    Wallet.objects.create(company=company, balance=balance)
    return company


def make_user(company, role='owner', email='o@x.test', **kwargs):
    user = User.objects.create_user(email, email, 'a-Strong-pass-77', **kwargs)
    Membership.objects.create(company=company, user=user, role=role)
    return user


class PricingRuleTests(SimpleTestCase):
    def test_the_owners_rule(self):
        # $1 of total cost sells at $1.50 with no fees; with failures and card fees the price rises to keep half the cost as profit.
        self.assertEqual(sale_price_usd('1', step='0.01'), Decimal('1.50'))
        self.assertEqual(sale_price_usd('0.0624', profit='0.5', failures='0.1', card_fees='0.06', step='0.01'), Decimal('0.12'))

    def test_rounding_is_up_and_once(self):
        self.assertEqual(catalog.price_points('generate_plan', 9), 190)
        self.assertEqual(catalog.price_points('generate_plan', 1), 70)
        # A plan of many posts is not priced as many one-post plans.
        self.assertLess(catalog.price_points('generate_plan', 9), 9 * catalog.price_points('generate_plan', 1))

    def test_every_service_has_a_price_or_is_free(self):
        for key in catalog.service_keys():
            if catalog.is_free(key):
                self.assertEqual(catalog.price_points(key), 0, key)
            else:
                self.assertGreater(catalog.price_points(key, 1), 0, key)

    def test_units_are_bounded(self):
        self.assertEqual(catalog.price_points('generate_plan', 999), catalog.price_points('generate_plan', 40))
        self.assertEqual(catalog.price_points('generate_plan', 0), catalog.price_points('generate_plan', 1))

    def test_packages_are_written_as_they_are(self):
        # A screenshot caught "$1 $25 $5": stripping zeros from '10' and '50' turned them into '1' and '5'.
        self.assertEqual([catalog.format_package(p) for p in catalog.topup_packages_usd()], ['10', '25', '50', '100'])
        self.assertEqual(catalog.format_package('2.50'), '2.5')
        with self.assertRaisesMessage(ValueError, '$10, $25, $50, $100'):
            catalog.topup_points(3)

    def test_topup_packages_are_only_the_listed_ones(self):
        self.assertEqual(catalog.topup_points(10), 10000)
        with self.assertRaises(ValueError):
            catalog.topup_points(3)


class QuoteTests(SimpleTestCase):
    def test_lines_add_up_to_the_total(self):
        for key in catalog.service_keys():
            for units in (None, 1, 9, 40):
                q = quotes.make(key, units)
                self.assertEqual(sum(line.points for line in q.lines), q.total, (key, units))

    def test_the_token_carries_the_total_and_cannot_be_forged(self):
        q = quotes.make('generate_plan', 9)
        data = quotes.read_token(q.token)
        self.assertEqual((data['s'], data['u'], data['t']), ('generate_plan', 9, 190))
        self.assertIsNone(quotes.read_token(q.token[:-3] + 'abc'))

    def test_a_bundle_shows_every_part_and_the_whole(self):
        q = quotes.bundle(quotes.make('rewrite_post'), quotes.make('generate_report'))
        self.assertEqual(q.total, 30 + 20)
        self.assertEqual([line.points for line in q.lines], [30, 20])


class ChargeTests(TestCase):
    def setUp(self):
        self.company = make_company(balance=1000)
        self.user = make_user(self.company)

    def test_charge_takes_exactly_the_quote_and_keeps_the_breakdown(self):
        q = quotes.make('generate_plan', 9)
        txn = charging.charge(self.company, self.user, q)
        self.assertEqual(txn.delta, -190)
        self.assertEqual(sum(b['points'] for b in txn.breakdown), 190)
        self.assertEqual(Wallet.objects.get(company=self.company).balance, 810)

    def test_a_price_that_differs_from_the_one_shown_charges_nothing(self):
        with self.assertRaises(charging.PriceChanged) as caught:
            charging.charge(self.company, self.user, quotes.make('generate_plan', 9), expected_total=80)
        self.assertEqual((caught.exception.shown, caught.exception.now), (80, 190))
        self.assertEqual(Wallet.objects.get(company=self.company).balance, 1000)
        self.assertFalse(WalletTransaction.objects.exists())

    def test_the_balance_never_goes_below_zero(self):
        wallet = Wallet.objects.get(company=self.company)
        wallet.balance = 100
        wallet.save()
        with self.assertRaises(charging.InsufficientCredits) as caught:
            charging.charge(self.company, self.user, quotes.make('generate_plan', 9))
        self.assertEqual((caught.exception.cost, caught.exception.balance), (190, 100))
        self.assertEqual(Wallet.objects.get(company=self.company).balance, 100)

    def test_a_refund_gives_back_once(self):
        txn = charging.charge(self.company, self.user, quotes.make('rewrite_post'))
        first = charging.refund(txn)
        self.assertEqual(first.delta, 30)
        self.assertIsNone(charging.refund(txn))                       # a second call does nothing
        self.assertEqual(Wallet.objects.get(company=self.company).balance, 1000)

    def test_free_services_exempt_companies_and_superusers_are_not_charged(self):
        self.assertIsNone(charging.charge(self.company, self.user, quotes.make('learn')))
        Wallet.objects.filter(company=self.company).update(is_exempt=True, balance=0)
        self.assertIsNone(charging.charge(self.company, self.user, quotes.make('generate_plan', 9)))
        Wallet.objects.filter(company=self.company).update(is_exempt=False)
        admin = User.objects.create_superuser('root', 'root@x.test', 'a-Strong-pass-77')
        self.assertIsNone(charging.charge(self.company, admin, quotes.make('generate_plan', 9)))
        self.assertFalse(WalletTransaction.objects.exists())


class JobChargeTests(TestCase):
    """Job.enqueue charges a paid kind at its quote; a failed or cancelled job gives the charge back."""

    def setUp(self):
        self.company = make_company(balance=1000)
        self.user = make_user(self.company)
        self.post = self.company.posts.create(title='x', platforms=['facebook'], created_by=self.user)

    def test_enqueue_charges_and_links_the_charge_to_the_job(self):
        job = Job.enqueue(self.company, Job.Kind.REWRITE_POST, self.user, post_id=self.post.pk, instruction='x')
        job.refresh_from_db()
        self.assertEqual(job.charge_txn.delta, -30)
        self.assertEqual(job.charge_txn.reference, f'job:{job.pk}')

    def test_a_plan_is_priced_by_its_posts(self):
        plan = ContentPlan.objects.create(company=self.company, month=datetime.date(2026, 12, 1), platforms=['facebook'], posts_per_week=2)
        job = Job.enqueue(self.company, Job.Kind.GENERATE_PLAN, self.user, plan_id=plan.pk)
        self.assertEqual(job.charge_txn.delta, -190)               # 9 posts in December at 2 a week
        self.assertEqual((job.charge_txn.units, job.charge_txn.service_key), (9, 'generate_plan'))

    def test_a_refused_payment_makes_no_job(self):
        Wallet.objects.filter(company=self.company).update(balance=5)
        with self.assertRaises(charging.InsufficientCredits):
            Job.enqueue(self.company, Job.Kind.REWRITE_POST, self.user, post_id=self.post.pk, instruction='x')
        self.assertFalse(Job.objects.exists())

    def test_free_kinds_cost_nothing(self):
        for kind in (Job.Kind.LEARN, Job.Kind.FETCH_INBOX, Job.Kind.RENDER_POST, Job.Kind.PUBLISH_POST, Job.Kind.FETCH_INSIGHTS):
            job = Job.enqueue(self.company, kind, self.user)
            self.assertIsNone(job.charge_txn)
        self.assertEqual(Wallet.objects.get(company=self.company).balance, 1000)

    def test_a_failed_job_gives_the_charge_back_and_a_done_one_keeps_it(self):
        from apps.ai.client import AIError
        failing = Job.enqueue(self.company, Job.Kind.REWRITE_POST, self.user, post_id=self.post.pk, instruction='x')
        with mock.patch.dict('apps.jobs.runner.HANDLERS', {Job.Kind.REWRITE_POST: mock.Mock(side_effect=AIError('خطأ'))}):
            run_job(failing)
        failing.refresh_from_db()
        self.assertEqual(failing.status, Job.Status.FAILED)
        self.assertEqual(Wallet.objects.get(company=self.company).balance, 1000)
        working = Job.enqueue(self.company, Job.Kind.REWRITE_POST, self.user, post_id=self.post.pk, instruction='x')
        with mock.patch.dict('apps.jobs.runner.HANDLERS', {Job.Kind.REWRITE_POST: mock.Mock(return_value='تم')}):
            run_job(working)
        self.assertEqual(Wallet.objects.get(company=self.company).balance, 970)

    def test_cancelling_gives_the_charge_back_once(self):
        job = Job.enqueue(self.company, Job.Kind.REWRITE_POST, self.user, post_id=self.post.pk, instruction='x')
        self.client.force_login(self.user)
        self.assertEqual(self.client.post(reverse('api:job_cancel', args=[job.pk])).status_code, 200)
        self.client.post(reverse('api:job_cancel', args=[job.pk]))
        self.assertEqual(Wallet.objects.get(company=self.company).balance, 1000)
        self.assertEqual(WalletTransaction.objects.filter(action='refund').count(), 1)


class PriceShownIsPriceChargedTests(TestCase):
    """The owner's rule (2026-11-18): the price a screen shows is the price that is charged. For every paid job kind, the
    price the screens work out (the same function the template tag uses) must equal what Job.enqueue deducts."""

    def test_for_every_paid_job_kind(self):
        company = make_company(balance=100_000)
        user = make_user(company)
        post = company.posts.create(title='x', platforms=['facebook'], created_by=user)
        plan = ContentPlan.objects.create(company=company, month=datetime.date(2026, 12, 1), platforms=['facebook'], posts_per_week=4)
        params = {'post_id': post.pk, 'plan_id': plan.pk, 'instruction': 'x', 'language': 'en', 'report_id': 1, 'analysis_id': 1, 'draft_id': 1}
        for kind, service in credit_jobs.SERVICES.items():
            shown = quotes.make(service, credit_jobs.units_for(kind, company, params)).total
            before = Wallet.objects.get(company=company).balance
            Job.enqueue(company, kind, user, expected_points=shown, **params)
            charged = before - Wallet.objects.get(company=company).balance
            self.assertEqual(charged, shown, kind)

    def test_a_stale_price_refuses_the_job(self):
        company = make_company(balance=1000)
        user = make_user(company)
        post = company.posts.create(title='x', platforms=['facebook'], created_by=user)
        with self.assertRaises(charging.PriceChanged):
            Job.enqueue(company, Job.Kind.REWRITE_POST, user, expected_points=8, post_id=post.pk, instruction='x')
        self.assertFalse(Job.objects.exists())
        self.assertEqual(Wallet.objects.get(company=company).balance, 1000)


class PaymentRefusedTests(TestCase):
    def setUp(self):
        self.company = make_company(balance=5)
        self.user = make_user(self.company)
        self.post = self.company.posts.create(title='x', platforms=['facebook'], created_by=self.user)
        self.client.force_login(self.user)
        self.client.cookies['wakeel_lang'] = 'en'

    def test_the_api_answers_402_with_the_message(self):
        r = self.client.post(reverse('api:post_rewrite', args=[self.post.pk]), {'instruction': 'x'}, content_type='application/json')
        self.assertEqual(r.status_code, 402)
        body = r.json()
        self.assertEqual((body['needed'], body['balance'], body['code']), (30, 5, 'insufficient_credits'))
        self.assertIn('$0.03', body['error'])
        self.assertFalse(Job.objects.exists())

    def test_a_stale_price_in_the_api_is_a_402_that_names_both_prices(self):
        Wallet.objects.filter(company=self.company).update(balance=1000)
        r = self.client.post(reverse('api:post_rewrite', args=[self.post.pk]), {'instruction': 'x', 'expected_points': 8},
                             content_type='application/json')
        self.assertEqual(r.status_code, 402)
        self.assertIn('$0.03', r.json()['error'])
        self.assertIn('$0.01', r.json()['error'])
        self.assertEqual(Wallet.objects.get(company=self.company).balance, 1000)

    def test_a_page_redirects_to_the_wallet_with_a_message_and_makes_no_plan(self):
        r = self.client.post(reverse('content:plan_create'), {'month': '2026-12-01', 'platforms': ['facebook'], 'posts_per_week': 4, 'brief': ''},
                             follow=True)
        self.assertRedirects(r, reverse('credits:wallet'))
        self.assertContains(r, 'Your balance is not enough')
        self.assertFalse(ContentPlan.objects.exists())              # nothing left stuck in "generating"
        self.assertFalse(Job.objects.exists())

    def test_the_plan_form_shows_the_price_and_posts_it_back(self):
        Wallet.objects.filter(company=self.company).update(balance=1000)
        page = self.client.get(reverse('content:plan_create')).content.decode()
        self.assertIn('id="expectedPoints"', page)
        self.assertIn('"9": 190', page)                              # the price table the screen works from
        month = (datetime.date.today().replace(day=1) + datetime.timedelta(days=32)).replace(day=1).isoformat()
        r = self.client.post(reverse('content:plan_create'), {'month': month, 'platforms': ['facebook'], 'posts_per_week': 4,
                                                              'brief': '', 'expected_points': 1})
        self.assertEqual(r.status_code, 302)                         # shown 1, charged more: refused, no plan
        self.assertFalse(ContentPlan.objects.exists())


class WalletPageTests(TestCase):
    def test_only_managers_see_the_wallet_and_the_price_list_and_ledger(self):
        company = make_company(balance=2500)
        owner = make_user(company)
        editor = make_user(company, 'editor', 'e@x.test')
        charging.charge(company, owner, quotes.make('generate_plan', 9))
        self.client.cookies['wakeel_lang'] = 'en'
        self.client.force_login(editor)
        self.assertEqual(self.client.get(reverse('credits:wallet')).status_code, 403)
        self.client.force_login(owner)
        page = self.client.get(reverse('credits:wallet')).content.decode()
        self.assertIn('$2.31', page)                                 # 2500 - 190 points
        self.assertIn('generate_plan', page)
        self.assertIn('/ 9 <bdi>post</bdi>', page)
        for amount in ('10', '25', '50', '100'):
            self.assertIn(f'>${amount}</span>', page)                     # the packages, as they are
        self.client.cookies['wakeel_lang'] = 'ar'
        self.assertIn('/ 9 <bdi>منشور</bdi>', self.client.get(reverse('credits:wallet')).content.decode())


class OpsWalletTests(TestCase):
    """The system admin funds a company by hand (until its operator's online payment is open) and sees what customers were charged."""

    def setUp(self):
        self.company = make_company(balance=0)
        self.owner = make_user(self.company)
        self.admin = User.objects.create_superuser('root', 'root@x.test', 'a-Strong-pass-77')
        self.client.cookies['wakeel_lang'] = 'en'

    def test_only_a_superuser_can_grant_and_the_grant_is_in_the_ledger(self):
        url = reverse('ops:wallet_grant', args=[self.company.pk])
        self.client.force_login(self.owner)
        self.assertEqual(self.client.post(url, {'amount': '10'}).status_code, 404)
        self.client.force_login(self.admin)
        self.client.post(url, {'amount': '10', 'note': 'pilot'})
        self.assertEqual(Wallet.objects.get(company=self.company).balance, 10000)
        txn = WalletTransaction.objects.get()
        self.assertEqual((txn.action, txn.delta, txn.user, txn.description), ('admin_grant', 10000, self.admin, 'pilot'))
        self.client.post(url, {'amount': '-2.5'})
        self.assertEqual(Wallet.objects.get(company=self.company).balance, 7500)
        for bad in ('', 'abc', '0', '5000'):
            self.client.post(url, {'amount': bad})
        self.assertEqual(Wallet.objects.get(company=self.company).balance, 7500)

    def test_an_exempt_company_is_not_charged(self):
        self.client.force_login(self.admin)
        self.client.post(reverse('ops:wallet_exempt', args=[self.company.pk]))
        self.assertTrue(Wallet.objects.get(company=self.company).is_exempt)
        post = self.company.posts.create(title='x', platforms=['facebook'], created_by=self.owner)
        job = Job.enqueue(self.company, Job.Kind.REWRITE_POST, self.owner, post_id=post.pk, instruction='x')
        self.assertIsNone(job.charge_txn)

    def test_revenue_is_what_was_charged_less_what_was_given_back(self):
        Wallet.objects.filter(company=self.company).update(balance=1000)
        a = charging.charge(self.company, self.owner, quotes.make('generate_plan', 9))     # 190
        charging.charge(self.company, self.owner, quotes.make('rewrite_post'))             # 30
        charging.refund(a)
        charged, refunded, net = charging.revenue_usd()
        self.assertEqual((charged, refunded, net), (Decimal('0.220'), Decimal('0.190'), Decimal('0.030')))
        self.client.force_login(self.admin)
        self.assertContains(self.client.get(reverse('ops:company', args=[self.company.pk])), '$0.03')
        self.assertContains(self.client.get(reverse('ops:usage')), 'wk-card adm-kpi')


class GuardTests(TestCase):
    def setUp(self):
        from . import guards
        guards.reset_cache()
        self.guards = guards
        self.company = make_company(balance=100_000)
        self.user = make_user(self.company)

    def tearDown(self):
        self.guards.reset_cache()

    @override_settings(AI_MONTHLY_BUDGET_USD=1)
    def test_the_platform_budget_stops_paid_jobs_for_everyone_but_superusers(self):
        post = self.company.posts.create(title='x', platforms=['facebook'], created_by=self.user)
        Job.objects.create(company=self.company, kind=Job.Kind.REWRITE_POST, cost_usd=Decimal('1.5'))
        with self.assertRaises(charging.InsufficientCredits) as caught:
            Job.enqueue(self.company, Job.Kind.REWRITE_POST, self.user, post_id=post.pk, instruction='x')
        self.assertEqual(caught.exception.code, 'budget_exhausted')
        admin = User.objects.create_superuser('root', 'root@x.test', 'a-Strong-pass-77')
        self.assertIsNotNone(Job.enqueue(self.company, Job.Kind.REWRITE_POST, admin, post_id=post.pk, instruction='x'))
        self.assertEqual(Wallet.objects.get(company=self.company).balance, 100_000)         # nothing was charged for the refused one

    @override_settings(AI_MAX_CHARGES_PER_HOUR=2)
    def test_a_company_cannot_run_unlimited_paid_jobs_in_an_hour(self):
        post = self.company.posts.create(title='x', platforms=['facebook'], created_by=self.user)
        for _n in range(2):
            Job.enqueue(self.company, Job.Kind.REWRITE_POST, self.user, post_id=post.pk, instruction='x')
        with self.assertRaises(charging.InsufficientCredits) as caught:
            Job.enqueue(self.company, Job.Kind.REWRITE_POST, self.user, post_id=post.pk, instruction='x')
        self.assertEqual(caught.exception.code, 'rate_limited')

    @override_settings(AI_MAX_REFUNDS_PER_DAY=2)
    def test_refunds_are_capped_because_a_refunded_job_still_cost_us(self):
        for _n in range(2):
            charging.refund(charging.charge(self.company, self.user, quotes.make('rewrite_post')))
        with self.assertRaises(charging.InsufficientCredits) as caught:
            charging.charge(self.company, self.user, quotes.make('rewrite_post'))
        self.assertEqual(caught.exception.code, 'rate_limited')

    @override_settings(AI_MONTHLY_BUDGET_USD=1)
    def test_the_message_is_plain_and_says_nothing_was_charged(self):
        from django.utils import translation

        from .middleware import refusal_message
        with translation.override('en'):
            text = refusal_message(charging.InsufficientCredits(30, 100, 'budget_exhausted'))
        self.assertIn('Nothing was charged', text)
        self.assertNotIn('budget', text.lower())
        with translation.override('ar'):
            self.assertIn('لم يُخصم شيء', refusal_message(charging.InsufficientCredits(30, 100, 'rate_limited')))
