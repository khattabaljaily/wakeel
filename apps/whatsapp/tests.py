import datetime
import hashlib
import hmac
import json
from unittest import mock

from django.test import TestCase, override_settings
from django.urls import reverse

from apps.content.models import ContentPlan, LearningSignal, Post, PostComment
from apps.content.tests import make_company, make_user

from . import services
from .models import ReviewSession

WA = dict(WHATSAPP_TOKEN='tok', WHATSAPP_PHONE_NUMBER_ID='555', WHATSAPP_ENABLED=True, WHATSAPP_APP_SECRET='shh',
          WHATSAPP_VERIFY_TOKEN='verify-me', SITE_URL='https://app.example')
CLIENT = '97455551234'


def button(payload, phone=CLIENT):
    return {'from': phone, 'type': 'interactive', 'interactive': {'type': 'button_reply', 'button_reply': {'id': payload, 'title': 'x'}}}


def text(body, phone=CLIENT):
    return {'from': phone, 'type': 'text', 'text': {'body': body}}


@override_settings(**WA)
@mock.patch('apps.whatsapp.client._send', return_value='wamid.1')
class ReviewFlowTests(TestCase):
    def setUp(self):
        self.company = make_company(client_whatsapp='+974 5555 1234')
        self.owner = make_user('o@example.com', self.company)
        self.plan = ContentPlan.objects.create(company=self.company, month=datetime.date(2026, 11, 1), platforms=['facebook'],
                                               status=ContentPlan.Status.READY, title='نوفمبر')
        self.post = Post.objects.create(company=self.company, plan=self.plan, title='منشور 1', caption='نص', platforms=['facebook'],
                                        status=Post.Status.REVIEW)
        self.done = Post.objects.create(company=self.company, plan=self.plan, title='معتمد', platforms=['facebook'],
                                        status=Post.Status.APPROVED)

    def sent(self, send):
        return [c.args[1] for c in send.call_args_list]

    def test_invite_sends_the_template_with_a_signed_start_button(self, send):
        services.invite(self.plan)
        to, payload = send.call_args.args
        self.assertEqual(to, CLIENT)
        self.assertEqual(payload['type'], 'template')
        start = payload['template']['components'][1]['parameters'][0]['payload']
        self.assertEqual(services.parse_button(start, CLIENT), ('start', self.plan.pk))
        self.assertIsNone(services.parse_button(start, '15550000000'))  # useless from another number
        self.plan.refresh_from_db()
        self.assertTrue(self.plan.share_token)
        self.assertTrue(ReviewSession.objects.filter(plan=self.plan, phone=CLIENT).exists())

    def test_start_sends_only_posts_awaiting_review(self, send):
        services.invite(self.plan)
        send.reset_mock()
        services.handle_message(button(services.button_id('start', self.plan.pk, CLIENT)))
        kinds = [p['type'] for p in self.sent(send)]
        self.assertEqual(kinds, ['text', 'interactive'])  # the intro, then the one post in review
        buttons = self.sent(send)[1]['interactive']['action']['buttons']
        self.assertEqual(services.parse_button(buttons[0]['reply']['id'], CLIENT), ('ap', self.post.pk))

    def test_approve_button(self, send):
        services.invite(self.plan)
        services.handle_message(button(services.button_id('ap', self.post.pk, CLIENT)))
        self.post.refresh_from_db()
        self.assertEqual(self.post.status, Post.Status.APPROVED)
        self.assertEqual(PostComment.objects.get(post=self.post).kind, PostComment.Kind.APPROVAL)

    def test_change_request_takes_the_next_text(self, send):
        services.invite(self.plan)
        services.handle_message(button(services.button_id('ch', self.post.pk, CLIENT)))
        services.handle_message(text('غيّروا الصورة لو سمحتم'))
        self.post.refresh_from_db()
        self.assertEqual(self.post.status, Post.Status.DRAFT)
        self.assertIn('غيّروا الصورة', self.post.review_note)
        self.assertEqual(PostComment.objects.get(post=self.post).kind, PostComment.Kind.CHANGES)
        self.assertTrue(LearningSignal.objects.filter(post=self.post, from_client=True).exists())
        self.assertIsNone(ReviewSession.objects.get().awaiting)
        # A later text is not taken as another change request; the client gets the link instead.
        services.handle_message(text('شكراً'))
        self.assertEqual(PostComment.objects.count(), 1)
        self.assertIn('/review/', self.sent(send)[-1]['text']['body'])

    def test_forged_or_foreign_buttons_do_nothing(self, send):
        services.invite(self.plan)
        services.handle_message(button(f'ap:{self.post.pk}:000000000000'))
        services.handle_message(button(services.button_id('ap', self.post.pk, '15550000000'), phone='15550000000'))
        self.post.refresh_from_db()
        self.assertEqual(self.post.status, Post.Status.REVIEW)

    def test_without_a_number_the_invite_fails_clearly(self, send):
        self.company.client_whatsapp = ''
        self.company.save()
        with self.assertRaises(services.WhatsAppError):
            services.invite(self.plan)
        send.assert_not_called()

    def test_plan_page_button_sends(self, send):
        self.client.force_login(self.owner)
        page = self.client.get(self.plan.get_absolute_url())
        self.assertContains(page, reverse('whatsapp:send_plan', args=[self.plan.pk]))
        self.client.post(reverse('whatsapp:send_plan', args=[self.plan.pk]))
        self.assertEqual(send.call_args.args[1]['type'], 'template')


@override_settings(**WA)
class WebhookTests(TestCase):
    def post(self, body, secret='shh'):
        raw = json.dumps(body).encode()
        sig = 'sha256=' + hmac.new(secret.encode(), raw, hashlib.sha256).hexdigest()
        return self.client.post(reverse('whatsapp:webhook'), raw, content_type='application/json', HTTP_X_HUB_SIGNATURE_256=sig)

    def test_verification(self):
        url = reverse('whatsapp:webhook')
        ok = self.client.get(url, {'hub.mode': 'subscribe', 'hub.verify_token': 'verify-me', 'hub.challenge': '42'})
        self.assertEqual(ok.content, b'42')
        self.assertEqual(self.client.get(url, {'hub.mode': 'subscribe', 'hub.verify_token': 'nope', 'hub.challenge': '42'}).status_code, 403)

    def test_signature_is_required(self):
        body = {'entry': []}
        self.assertEqual(self.post(body, secret='wrong').status_code, 403)
        with mock.patch('apps.whatsapp.services.handle_payload') as handle:
            self.assertEqual(self.post(body).status_code, 200)
        handle.assert_called_once_with(body)

    def test_messages_reach_the_handler(self):
        body = {'entry': [{'changes': [{'value': {'metadata': {'phone_number_id': '555'}, 'messages': [text('hi')]}},
                                       {'value': {'metadata': {'phone_number_id': '999'}, 'messages': [text('other number')]}}]}]}
        with mock.patch('apps.whatsapp.services.handle_message') as handle:
            self.post(body)
        handle.assert_called_once_with(text('hi'))
