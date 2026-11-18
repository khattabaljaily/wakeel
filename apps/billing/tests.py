import hashlib
from decimal import Decimal
import hmac
import json
import time
from unittest import mock

from django.test import TestCase, override_settings
from django.urls import reverse

from apps.accounts.models import User
from apps.credits.charging import get_wallet
from apps.credits.models import WalletTransaction
from apps.companies import operators as company_operators
from apps.companies.models import Company, Membership
from apps.billing import gateways as billing_gateways

from enjaz_operators.gateways import Checkout
from enjaz_operators.gateways import stripe as stripe_gateway
from .models import Payment

SECRET = 'whsec_test_secret'


def stripe_operator_for_tests(testcase):
    """Wakeel's operator is Banan, whose gateway (SkipCash) does not exist yet. These tests exercise the Stripe mechanism with
    an operator that has one (JOVIA, registered for MyDocHub)."""
    for module in (company_operators, billing_gateways):
        patcher = mock.patch.object(module, 'PRODUCT', 'mydochub')
        patcher.start()
        testcase.addCleanup(patcher.stop)


def signed(event, secret=SECRET, stamp=None):
    payload = json.dumps(event).encode()
    stamp = int(time.time()) if stamp is None else stamp
    mac = hmac.new(secret.encode(), f'{stamp}.'.encode() + payload, hashlib.sha256).hexdigest()
    return payload, f't={stamp},v1={mac}'


FULL = {'jovia': {'secret_key': 'sk_test_x', 'webhook_secret': SECRET}}
HOOK_ONLY = {'jovia': {'webhook_secret': SECRET}}
HOOK_ONLY_EMPTY = {}


@override_settings(GATEWAY_KEYS=FULL, PAYMENT_LINKS={}, SITE_URL='https://app.example.com')
class BillingTests(TestCase):
    def setUp(self):
        stripe_operator_for_tests(self)
        self.company = Company.objects.create(name='Alpha', industry='x', country='Qatar', operator='jovia')
        self.owner = User.objects.create_user('o@example.com', 'o@example.com', 'a-Strong-pass-77')
        self.viewer = User.objects.create_user('v@example.com', 'v@example.com', 'a-Strong-pass-77')
        Membership.objects.create(company=self.company, user=self.owner, role='owner')
        Membership.objects.create(company=self.company, user=self.viewer, role='viewer')
        self.client.force_login(self.owner)

    def pay(self, amount='25'):
        with mock.patch('enjaz_operators.gateways.stripe.StripeGateway.checkout',
                        return_value=Checkout(reference='cs_test_1', url='https://checkout.stripe.com/pay/cs_test_1')) as call:
            response = self.client.post(reverse('billing:checkout'), {'amount': amount})
        return response, call

    def event(self, payment, kind='checkout.session.completed', **session):
        return {'type': kind, 'data': {'object': {
            'client_reference_id': str(payment.pk), 'payment_status': 'paid', 'amount_total': int(payment.amount_usd * 100),
            'currency': 'usd', **session}}}

    def send(self, event, **kwargs):
        payload, header = signed(event, **kwargs)
        return self.client.post(reverse('billing:operator_webhook', args=['jovia']), payload, content_type='application/json', HTTP_STRIPE_SIGNATURE=header)

    def test_choosing_a_package_opens_stripe_with_the_right_amount_and_nothing_is_credited_yet(self):
        response, call = self.pay('25')
        self.assertRedirects(response, 'https://checkout.stripe.com/pay/cs_test_1', fetch_redirect_response=False)
        payment = Payment.objects.get()
        self.assertEqual((payment.amount_usd, payment.points, payment.status, payment.stripe_session_id), (25, 25000, 'created', 'cs_test_1'))
        self.assertEqual((payment.operator, payment.currency), ('jovia', 'USD'))            # through the company's operator
        self.assertEqual((call.call_args.kwargs['amount'], call.call_args.kwargs['currency']), (payment.amount_usd, 'USD'))
        self.assertEqual(call.call_args.kwargs['success_url'], 'http://testserver/company/wallet/?paid=1')
        self.assertEqual(get_wallet(self.company).balance, 0)

    def test_only_the_packages_only_managers_and_only_when_stripe_is_set_up(self):
        for amount in ('7', '0', '-10', 'abc', '10.5'):
            self.pay(amount)
        self.assertFalse(Payment.objects.exists())
        self.client.force_login(self.viewer)
        self.pay('10')
        self.assertFalse(Payment.objects.exists())
        self.client.force_login(self.owner)
        with override_settings(GATEWAY_KEYS=HOOK_ONLY_EMPTY):
            self.pay('10')
        self.assertFalse(Payment.objects.exists())

    def test_a_confirmed_payment_adds_the_credit_once_even_if_stripe_repeats_the_message(self):
        self.pay('10')
        payment = Payment.objects.get()
        for _n in range(3):
            self.assertEqual(self.send(self.event(payment)).status_code, 200)
        self.assertEqual(get_wallet(self.company).balance, 10000)
        self.assertEqual(WalletTransaction.objects.filter(action='topup').count(), 1)
        payment.refresh_from_db()
        self.assertEqual((payment.status, payment.paid_at is not None), ('paid', True))

    def test_a_message_that_is_not_from_stripe_or_does_not_match_credits_nothing(self):
        self.pay('10')
        payment = Payment.objects.get()
        self.assertEqual(self.send(self.event(payment), secret='whsec_someone_else').status_code, 400)
        self.assertEqual(self.send(self.event(payment), stamp=int(time.time()) - 3600).status_code, 400)
        self.assertEqual(self.client.post(reverse('billing:operator_webhook', args=['jovia']), b'{}', content_type='application/json').status_code, 400)
        self.send(self.event(payment, amount_total=100))                    # paid less than the package
        self.send(self.event(payment, payment_status='unpaid'))
        self.send(self.event(payment, currency='eur'))
        self.assertEqual(get_wallet(self.company).balance, 0)

    def test_an_expired_session_is_marked_and_unknown_payments_are_ignored(self):
        self.pay('10')
        payment = Payment.objects.get()
        self.send(self.event(payment, kind='checkout.session.expired'))
        payment.refresh_from_db()
        self.assertEqual(payment.status, 'expired')
        self.assertEqual(self.send({'type': 'checkout.session.completed', 'data': {'object': {'client_reference_id': '999'}}}).status_code, 200)
        self.assertEqual(self.send({'type': 'invoice.paid', 'data': {'object': {}}}).status_code, 200)
        self.assertEqual(get_wallet(self.company).balance, 0)

    def test_the_balance_page_opens_the_pay_buttons_only_when_payment_is_set_up(self):
        page = self.client.get(reverse('credits:wallet')).content.decode()
        self.assertIn(reverse('billing:checkout'), page)
        with override_settings(GATEWAY_KEYS=HOOK_ONLY_EMPTY):
            page = self.client.get(reverse('credits:wallet')).content.decode()
            self.assertNotIn(reverse('billing:checkout'), page)
            self.assertEqual(self.client.post(reverse('billing:operator_webhook', args=['jovia']), b'{}', content_type='application/json').status_code, 404)

    def test_the_form_encoding_matches_what_stripe_reads(self):
        pairs = dict(stripe_gateway.flat({'a': {'b': 1}, 'line_items': [{'quantity': 1, 'price_data': {'unit_amount': 500}}]}))
        self.assertEqual(pairs, {'a[b]': 1, 'line_items[0][quantity]': 1, 'line_items[0][price_data][unit_amount]': 500})

    def test_an_operator_may_only_settle_its_own_payments(self):
        self.pay('10')
        jovias = Payment.objects.get()
        banans = Payment.objects.create(company=self.company, user=self.owner, amount_usd=10, points=10000, operator='banan')
        self.send(self.event(banans))                                       # signed with JOVIA's secret, about Banan's payment
        banans.refresh_from_db()
        self.assertEqual(banans.status, 'created')
        payload, header = signed(self.event(jovias))                        # Banan has no gateway here: its address answers 404
        url = reverse('billing:operator_webhook', args=['banan'])
        self.assertEqual(self.client.post(url, payload, content_type='application/json', HTTP_STRIPE_SIGNATURE=header).status_code, 404)
        url = reverse('billing:operator_webhook', args=['jovia'])          # JOVIA's own address works like the first one
        self.assertEqual(self.client.post(url, payload, content_type='application/json', HTTP_STRIPE_SIGNATURE=header).status_code, 200)
        self.assertEqual(get_wallet(self.company).balance, 10000)

    def test_the_keys_can_come_per_operator_from_the_gateways_block(self):
        with override_settings(GATEWAY_KEYS={'jovia': {'secret_key': 'sk_test_y', 'webhook_secret': SECRET}}):
            self.assertIn(reverse('billing:checkout'), self.client.get(reverse('credits:wallet')).content.decode())
            self.pay('10')
            self.send(self.event(Payment.objects.get()))
        self.assertEqual(get_wallet(self.company).balance, 10000)



LINKS = {'jovia': {'10': 'https://buy.stripe.com/test_10', '25': 'https://buy.stripe.com/test_25', '50': ''}}


@override_settings(GATEWAY_KEYS=HOOK_ONLY, PAYMENT_LINKS=LINKS, SITE_URL='https://app.example.com')
class PaymentLinkTests(TestCase):
    """Stripe payment links (one per package): no secret key, only the webhook's. The link names the payment, the webhook
    credits it once and at its own price."""

    def setUp(self):
        stripe_operator_for_tests(self)
        self.company = Company.objects.create(name='Alpha', industry='x', country='Qatar', operator='jovia')
        self.owner = User.objects.create_user('o@example.com', 'o@example.com', 'a-Strong-pass-77')
        Membership.objects.create(company=self.company, user=self.owner, role='owner')
        self.client.force_login(self.owner)

    def send(self, payment, amount_cents=None):
        event = {'type': 'checkout.session.completed', 'data': {'object': {
            'client_reference_id': str(payment.pk), 'payment_status': 'paid', 'currency': 'usd', 'payment_link': 'plink_1',
            'amount_total': int(payment.amount_usd * 100) if amount_cents is None else amount_cents}}}
        payload, header = signed(event)
        return self.client.post(reverse('billing:operator_webhook', args=['jovia']), payload, content_type='application/json', HTTP_STRIPE_SIGNATURE=header)

    def test_a_package_with_a_link_opens_it_naming_the_payment(self):
        response = self.client.post(reverse('billing:checkout'), {'amount': '25'})
        payment = Payment.objects.get()
        self.assertEqual(response['Location'], f'https://buy.stripe.com/test_25?client_reference_id={payment.pk}&prefilled_email=o%40example.com')
        self.assertEqual((payment.amount_usd, payment.points, payment.status, payment.operator), (25, 25000, 'created', 'jovia'))
        self.assertEqual(get_wallet(self.company).balance, 0)

    def test_the_paid_link_is_credited_once_and_only_at_its_price(self):
        self.client.post(reverse('billing:checkout'), {'amount': '10'})
        payment = Payment.objects.get()
        self.assertEqual(self.send(payment, amount_cents=500).status_code, 200)      # not the package's price
        self.assertEqual(get_wallet(self.company).balance, 0)
        self.send(payment)
        self.send(payment)                                                          # Stripe may send it twice
        payment.refresh_from_db()
        self.assertEqual((payment.status, get_wallet(self.company).balance), (Payment.PAID, 10000))
        self.assertEqual(WalletTransaction.objects.filter(action=WalletTransaction.TOPUP).count(), 1)

    def test_the_balance_page_sells_by_link_and_a_package_without_one_is_not_sold(self):
        self.assertIn(reverse('billing:checkout'), self.client.get(reverse('credits:wallet')).content.decode())
        self.client.post(reverse('billing:checkout'), {'amount': '50'})            # no link and no secret key
        self.assertFalse(Payment.objects.exists())

    def test_without_links_or_without_the_webhook_secret_payments_stay_closed(self):
        for overrides in ({'PAYMENT_LINKS': {'jovia': {'10': '', '25': '', '50': ''}}}, {'GATEWAY_KEYS': {}}):
            with self.subTest(overrides=overrides), override_settings(**overrides):
                self.assertNotIn(reverse('billing:checkout'), self.client.get(reverse('credits:wallet')).content.decode())
                self.client.post(reverse('billing:checkout'), {'amount': '10'})
                self.assertFalse(Payment.objects.exists())
                self.assertEqual(self.client.post(reverse('billing:operator_webhook', args=['jovia']), b'{}', content_type='application/json').status_code, 404)
