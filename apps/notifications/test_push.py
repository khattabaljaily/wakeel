import json
from unittest import mock

from django.test import TestCase, override_settings
from django.urls import reverse

from apps.accounts.models import User
from apps.content.tests import make_company, make_user

from .models import PushSubscription
from .services import notify

# A throwaway key pair, only for these tests.
TEST_PRIVATE = 'MIGHAgEAMBMGByqGSM49AgEGCCqGSM49AwEHBG0wawIBAQQgE-SLmzsx3tkR3JyMqCZtGBicDSdUFbj74z7O6redRFOhRANCAARan09eX4BjnAu6Kfit_RZrK6HE_djoXIlcpBExGFDL_9dgRBoSmNTOAxgTu3GBspo2Jk86dayaXXFG8tl9BfEt'


class PwaTests(TestCase):
    def test_manifest_worker_and_offline_page(self):
        m = self.client.get(reverse('core:manifest'))
        data = json.loads(m.content)
        self.assertEqual((data['short_name'], data['dir'], data['display']), ('وكيل', 'rtl', 'standalone'))
        self.assertTrue(any(i['purpose'] == 'maskable' for i in data['icons']))
        sw = self.client.get(reverse('core:service_worker'))
        self.assertEqual(sw['Content-Type'], 'application/javascript')
        self.assertEqual(sw['Service-Worker-Allowed'], '/')
        self.assertContains(sw, "addEventListener('push'")
        self.assertContains(self.client.get(reverse('core:offline')), 'لا يوجد اتصال')

    def test_pending_accounts_can_still_load_the_worker(self):
        user = User.objects.create_user(username='p@x.test', email='p@x.test', password='Strong-pass-123')
        user.is_approved = False
        user.save()
        self.client.force_login(user)
        self.assertEqual(self.client.get(reverse('core:service_worker')).status_code, 200)


@override_settings(VAPID_PUBLIC_KEY='test-public', VAPID_PRIVATE_KEY=TEST_PRIVATE, PUSH_IN_BACKGROUND=False)
class PushTests(TestCase):
    def setUp(self):
        self.company = make_company()
        self.user = make_user('u@x.test', self.company)
        self.client.force_login(self.user)
        self.sub = {'endpoint': 'https://push.example.com/abc', 'keys': {'p256dh': 'BKEY', 'auth': 'AUTH'}}

    def test_subscribe_and_unsubscribe(self):
        url = reverse('notifications:push_subscribe')
        self.assertEqual(self.client.post(url, self.sub, content_type='application/json').status_code, 200)
        self.client.post(url, self.sub, content_type='application/json')  # same device again: still one row
        self.assertEqual(PushSubscription.objects.filter(user=self.user).count(), 1)
        bad = dict(self.sub, endpoint='http://insecure.example.com/x')
        self.assertEqual(self.client.post(url, bad, content_type='application/json').status_code, 400)
        self.client.post(reverse('notifications:push_unsubscribe'), {'endpoint': self.sub['endpoint']}, content_type='application/json')
        self.assertFalse(PushSubscription.objects.exists())

    @mock.patch('pywebpush.webpush')
    def test_notifications_are_pushed_and_dead_devices_dropped(self, webpush):
        from pywebpush import WebPushException
        PushSubscription.objects.create(user=self.user, endpoint='https://push.example.com/1', endpoint_hash='1', p256dh='k', auth='a')
        PushSubscription.objects.create(user=self.user, endpoint='https://push.example.com/2', endpoint_hash='2', p256dh='k', auth='a')

        def fake(info, payload, **kw):
            if info['endpoint'].endswith('/2'):
                raise WebPushException('gone', response=mock.Mock(status_code=410))
            self.payload = json.loads(payload)
        webpush.side_effect = fake
        notify([self.user], self.company, 'خطة أكتوبر جاهزة', '/app/plans/1/')
        self.assertEqual(webpush.call_count, 2)
        self.assertEqual((self.payload['title'], self.payload['body'], self.payload['url']),
                         (self.company.name, 'خطة أكتوبر جاهزة', '/app/plans/1/'))
        self.assertEqual(list(PushSubscription.objects.values_list('endpoint', flat=True)), ['https://push.example.com/1'])
