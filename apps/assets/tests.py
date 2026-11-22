import datetime
import io
import json
from unittest import mock

from django.test import TestCase
from django.urls import reverse
from django.utils import timezone

from apps.companies.models import Membership
from apps.content.tests import make_company, make_user
from apps.notifications.models import Notification

from . import checks, reminders
from .models import Asset


def days(n):
    return timezone.localdate() + datetime.timedelta(days=n)


class AssetTests(TestCase):
    def setUp(self):
        self.company = make_company('A')
        self.other = make_company('B')
        self.owner = make_user('o@example.com', self.company)
        self.viewer = make_user('v@example.com', self.company, Membership.Role.VIEWER)
        self.stranger = make_user('s@example.com', self.other)

    def make(self, **kwargs):
        data = {'company': self.company, 'kind': Asset.DOMAIN, 'name': 'example.com', 'identifier': 'example.com'}
        data.update(kwargs)
        return Asset.all_companies.create(**data)

    def post_new(self, **kwargs):
        data = {'kind': 'domain', 'name': 'example.com', 'currency': 'usd', 'cycle': 'yearly'}
        data.update(kwargs)
        return self.client.post(reverse('assets:new'), data)

    def test_add_asset_keeps_company_and_creator(self):
        self.client.force_login(self.owner)
        response = self.post_new(cost='12.50', expiry_date=str(days(100)))
        self.assertRedirects(response, reverse('assets:list'))
        asset = Asset.all_companies.get()
        self.assertEqual((asset.company, asset.created_by, asset.currency), (self.company, self.owner, 'USD'))

    def test_viewer_cannot_add_or_delete(self):
        asset = self.make()
        self.client.force_login(self.viewer)
        self.post_new()
        self.client.post(reverse('assets:delete', args=[asset.pk]))
        self.assertEqual(Asset.all_companies.count(), 1)

    def test_company_never_sees_another_companys_assets(self):
        asset = self.make()
        self.client.force_login(self.stranger)
        self.assertNotContains(self.client.get(reverse('assets:list')), 'example.com')
        self.assertEqual(self.client.get(reverse('assets:edit', args=[asset.pk])).status_code, 404)
        self.client.post(reverse('assets:delete', args=[asset.pk]))
        self.assertTrue(Asset.all_companies.filter(pk=asset.pk).exists())

    def test_responsible_must_be_a_member_of_the_company(self):
        self.client.force_login(self.owner)
        response = self.post_new(responsible=self.stranger.pk)
        self.assertEqual(response.status_code, 200)
        self.assertFalse(Asset.all_companies.exists())

    def test_expiry_before_start_is_refused(self):
        self.client.force_login(self.owner)
        self.post_new(start_date=str(days(10)), expiry_date=str(days(5)))
        self.assertFalse(Asset.all_companies.exists())

    def test_changing_the_date_starts_the_reminders_again(self):
        asset = self.make(expiry_date=days(5), reminded_days=7)
        self.client.force_login(self.owner)
        self.client.post(reverse('assets:edit', args=[asset.pk]), {
            'kind': 'domain', 'name': 'example.com', 'currency': 'USD', 'cycle': 'yearly', 'expiry_date': str(days(365))})
        asset.refresh_from_db()
        self.assertIsNone(asset.reminded_days)

    def test_status_and_yearly_cost(self):
        self.assertEqual(self.make(expiry_date=days(-1)).status, 'expired')
        self.assertEqual(self.make(expiry_date=days(10)).status, 'soon')
        self.assertEqual(self.make(expiry_date=days(100)).status, 'valid')
        self.assertEqual(self.make().status, '')
        self.assertEqual(self.make(cost=10, cycle=Asset.MONTHLY).yearly_cost, 120)
        self.assertIsNone(self.make(cost=10, cycle=Asset.ONCE).yearly_cost)

    def test_list_filters_and_totals(self):
        self.make(name='late.com', expiry_date=days(3), cost=100, currency='USD')
        self.make(name='far.com', expiry_date=days(300), cost=50, currency='USD')
        self.make(name='box', kind=Asset.HOSTING, identifier='')
        self.client.force_login(self.owner)
        soon = self.client.get(reverse('assets:list') + '?status=soon')
        self.assertContains(soon, 'late.com')
        self.assertNotContains(soon, 'far.com')
        self.assertEqual([a.name for a in self.client.get(reverse('assets:list') + '?kind=hosting').context['assets']], ['box'])
        self.assertEqual(self.client.get(reverse('assets:list')).context['yearly_totals'], [('USD', 150)])

    def test_menu_badge_counts_what_is_due(self):
        self.make(name='late.com', expiry_date=days(-2))
        self.make(name='far.com', expiry_date=days(300))
        self.client.force_login(self.owner)
        self.assertEqual(self.client.get(reverse('assets:list')).context['asset_alerts'], 1)


class ReminderTests(TestCase):
    def setUp(self):
        self.company = make_company('A')
        self.owner = make_user('o@example.com', self.company)
        self.member = make_user('m@example.com', self.company, Membership.Role.EDITOR)

    def make(self, **kwargs):
        data = {'company': self.company, 'kind': Asset.LICENSE, 'name': 'Office'}
        data.update(kwargs)
        return Asset.all_companies.create(**data)

    def test_stage_for_each_distance(self):
        today = timezone.localdate()
        for left, expected in ((120, None), (90, 90), (45, 90), (30, 30), (8, 30), (7, 7), (1, 1), (0, 0), (-5, 0)):
            self.assertEqual(reminders.stage(self.make(expiry_date=today + datetime.timedelta(days=left)), today), expected, left)

    def test_each_stage_is_sent_once(self):
        asset = self.make(expiry_date=days(25))
        self.assertGreater(reminders.send_due(), 0)
        asset.refresh_from_db()
        self.assertEqual(asset.reminded_days, 30)
        self.assertEqual(reminders.send_due(), 0)
        self.assertEqual(Notification.objects.filter(user=self.owner, kind='expiring').count(), 1)

    def test_responsible_member_is_told_too(self):
        self.make(expiry_date=days(5), responsible=self.member)
        reminders.send_due()
        self.assertTrue(Notification.objects.filter(user=self.member, kind='expiring').exists())
        self.assertTrue(Notification.objects.filter(user=self.owner, kind='expiring').exists())

    def test_late_asset_says_expired(self):
        self.make(expiry_date=days(-3))
        reminders.send_due()
        self.assertTrue(Notification.objects.filter(user=self.owner, kind='expired').exists())

    def test_no_date_no_reminder(self):
        self.make()
        self.assertEqual(reminders.send_due(), 0)


class DomainCheckTests(TestCase):
    def setUp(self):
        self.company = make_company('A')
        self.owner = make_user('o@example.com', self.company)

    def asset(self, **kwargs):
        data = {'company': self.company, 'kind': Asset.DOMAIN, 'name': 'example.com', 'identifier': 'example.com'}
        data.update(kwargs)
        return Asset.all_companies.create(**data)

    def rdap(self, payload):
        response = mock.MagicMock()
        response.__enter__.return_value = io.BytesIO(json.dumps(payload).encode())
        return mock.patch('apps.assets.checks.urllib.request.urlopen', return_value=response)

    def test_hostname_is_cleaned_and_validated(self):
        self.assertEqual(checks.hostname('HTTPS://User@Example.com:8443/a?b=1'), 'example.com')
        for bad in ('', 'localhost', '10.0.0.1', 'a b.com', 'http://', '-x.com'):
            with self.assertRaises(checks.CheckError, msg=bad):
                checks.hostname(bad)

    def test_reads_the_registry_date_and_restarts_reminders(self):
        asset = self.asset(expiry_date=days(5), reminded_days=7)
        with self.rdap({'events': [{'eventAction': 'registration', 'eventDate': '2020-01-01T00:00:00Z'},
                                   {'eventAction': 'expiration', 'eventDate': '2031-03-04T10:00:00Z'}]}):
            self.assertTrue(checks.run(asset))
        asset.refresh_from_db()
        self.assertEqual((asset.expiry_date, asset.check_status, asset.reminded_days), (datetime.date(2031, 3, 4), 'ok', None))

    def test_a_failed_check_keeps_the_typed_date(self):
        asset = self.asset(expiry_date=days(50))
        with self.rdap({'events': []}):
            self.assertFalse(checks.run(asset))
        asset.refresh_from_db()
        self.assertEqual((asset.expiry_date, asset.check_status), (days(50), 'failed'))
        self.assertTrue(asset.check_note)

    def test_only_domains_are_checked(self):
        with mock.patch('apps.assets.checks.urllib.request.urlopen') as opened:
            self.assertFalse(checks.run(self.asset(kind=Asset.SSL)))
            self.assertFalse(checks.run(self.asset(identifier='')))
        opened.assert_not_called()

    def test_check_button(self):
        asset = self.asset()
        self.client.force_login(self.owner)
        with self.rdap({'events': [{'eventAction': 'expiration', 'eventDate': '2031-03-04T10:00:00Z'}]}):
            self.client.post(reverse('assets:check', args=[asset.pk]))
        asset.refresh_from_db()
        self.assertEqual(asset.expiry_date, datetime.date(2031, 3, 4))
