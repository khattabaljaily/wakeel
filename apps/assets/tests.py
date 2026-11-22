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

from apps.audit.models import AuditEvent
from django.core import mail

from . import checks, digest, reminders, services
from .models import Asset, AssetCalendar, RenewalLog


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


# ---------------------------------------------------------------------------------------------------- renewal

class RenewTests(TestCase):
    def setUp(self):
        self.company = make_company('A')
        self.other = make_company('B')
        self.owner = make_user('o@example.com', self.company)
        self.viewer = make_user('v@example.com', self.company, Membership.Role.VIEWER)
        self.stranger = make_user('s@example.com', self.other)

    def make(self, **kwargs):
        data = {'company': self.company, 'kind': Asset.DOMAIN, 'name': 'example.com', 'expiry_date': days(10), 'cost': 45}
        data.update(kwargs)
        return Asset.all_companies.create(**data)

    def test_add_months_keeps_the_last_day_of_a_short_month(self):
        self.assertEqual(services.add_months(datetime.date(2027, 1, 31), 1), datetime.date(2027, 2, 28))
        self.assertEqual(services.add_months(datetime.date(2028, 1, 31), 1), datetime.date(2028, 2, 29))
        self.assertEqual(services.add_months(datetime.date(2027, 12, 15), 1), datetime.date(2028, 1, 15))
        self.assertEqual(services.add_months(datetime.date(2028, 2, 29), 12), datetime.date(2029, 2, 28))

    def test_next_date_is_a_cycle_later_and_never_in_the_past(self):
        today = datetime.date(2026, 6, 1)
        self.assertEqual(services.next_date(self.make(expiry_date=datetime.date(2026, 6, 10)), today), datetime.date(2027, 6, 10))
        self.assertEqual(services.next_date(self.make(expiry_date=datetime.date(2026, 6, 10), cycle=Asset.MONTHLY), today), datetime.date(2026, 7, 10))
        late = self.make(expiry_date=datetime.date(2026, 1, 15), cycle=Asset.MONTHLY)
        self.assertEqual(services.next_date(late, today), datetime.date(2026, 6, 15))       # forgotten for months: the next future date
        with self.assertRaises(services.CannotRenew):
            services.next_date(self.make(cycle=Asset.ONCE))
        with self.assertRaises(services.CannotRenew):
            services.next_date(self.make(expiry_date=None))

    def test_renew_moves_the_date_restarts_reminders_and_logs_it(self):
        asset = self.make(expiry_date=days(5), reminded_days=7)
        self.client.force_login(self.owner)
        response = self.client.post(reverse('assets:renew', args=[asset.pk]))
        self.assertRedirects(response, reverse('assets:list'))
        asset.refresh_from_db()
        self.assertEqual((asset.expiry_date, asset.reminded_days), (services.add_months(days(5), 12), None))
        log = RenewalLog.all_companies.get()
        self.assertEqual((log.asset, log.old_expiry, log.new_expiry, log.cost, log.by), (asset, days(5), asset.expiry_date, 45, self.owner))
        self.assertTrue(AuditEvent.objects.for_company(self.company).filter(action=AuditEvent.ASSET_RENEWED).exists())

    def test_a_one_time_cost_cannot_be_renewed(self):
        asset = self.make(cycle=Asset.ONCE)
        self.client.force_login(self.owner)
        self.client.post(reverse('assets:renew', args=[asset.pk]))
        self.assertFalse(RenewalLog.all_companies.exists())

    def test_only_editors_of_the_same_company_renew(self):
        asset = self.make()
        for user in (self.viewer, self.stranger):
            self.client.force_login(user)
            self.client.post(reverse('assets:renew', args=[asset.pk]))
        self.assertFalse(RenewalLog.all_companies.exists())
        self.assertEqual(Asset.all_companies.get().expiry_date, days(10))

    def test_history_shows_on_the_edit_page(self):
        asset = self.make()
        self.client.force_login(self.owner)
        self.client.post(reverse('assets:renew', args=[asset.pk]))
        page = self.client.get(reverse('assets:edit', args=[asset.pk]))
        self.assertEqual(len(page.context['renewals']), 1)


# ---------------------------------------------------------------------------------------------------- import

class ImportTests(TestCase):
    HEAD = 'name,type,provider,address,account,start_date,renewal_date,auto_renew,cost,currency,billing,responsible,notes\n'

    def setUp(self):
        self.company = make_company('A')
        self.other = make_company('B')
        self.owner = make_user('o@example.com', self.company)
        self.viewer = make_user('v@example.com', self.company, Membership.Role.VIEWER)
        self.stranger = make_user('s@example.com', self.other)

    def upload(self, text, user=None):
        from django.core.files.uploadedfile import SimpleUploadedFile
        self.client.force_login(user or self.owner)
        data = text if isinstance(text, bytes) else text.encode('utf-8')
        return self.client.post(reverse('assets:import'), {'file': SimpleUploadedFile('assets.csv', data, content_type='text/csv')})

    def test_valid_rows_are_saved_for_the_company(self):
        self.upload(self.HEAD + 'a.com,domain,GoDaddy,a.com,,,2027-03-14,yes,45,usd,yearly,o@example.com,\n'
                                'Office,license,,,,,2027-01-01,,300,USD,Monthly,,\n')
        assets = {a.name: a for a in Asset.all_companies.all()}
        self.assertEqual(len(assets), 2)
        a = assets['a.com']
        self.assertEqual((a.company, a.kind, a.auto_renew, a.currency, a.responsible, a.expiry_date), (self.company, 'domain', True, 'USD', self.owner, datetime.date(2027, 3, 14)))
        self.assertEqual(assets['Office'].cycle, Asset.MONTHLY)          # the name of the choice works as well as its key
        self.assertFalse(assets['Office'].auto_renew)

    def test_wrong_rows_are_reported_and_skipped_the_rest_saved(self):
        response = self.upload(self.HEAD + 'ok.com,domain,,,,,2027-03-14,,,USD,yearly,,\n'
                                           'bad1,spaceship,,,,,,,,USD,yearly,,\n'
                                           'bad2,domain,,,,,not-a-date,,,USD,yearly,,\n'
                                           'bad3,domain,,,,,,,,USD,yearly,nobody@example.com,\n')
        self.assertEqual([a.name for a in Asset.all_companies.all()], ['ok.com'])
        self.assertEqual([n for n, _ in response.context['problems']], [3, 4, 5])

    def test_a_member_of_another_company_cannot_be_responsible(self):
        self.upload(self.HEAD + f'x.com,domain,,,,,,,,USD,yearly,{self.stranger.email},\n')
        self.assertFalse(Asset.all_companies.exists())

    def test_semicolons_and_excel_marks_are_accepted(self):
        self.upload('﻿name;type;renewal_date;cost\nsemi.com;domain;2027-05-05;12,50\n')
        a = Asset.all_companies.get()
        self.assertEqual((a.name, str(a.cost)), ('semi.com', '12.50'))

    def test_files_that_cannot_be_read_add_nothing(self):
        self.upload(b'\xff\xfe\x00bad')
        self.upload('no,header,here\n1,2,3\n')
        self.upload(b'x' * (1024 * 1024 + 10))
        self.assertFalse(Asset.all_companies.exists())

    def test_viewers_cannot_import_and_the_template_downloads(self):
        self.upload(self.HEAD + 'v.com,domain,,,,,,,,USD,yearly,,\n', user=self.viewer)
        self.assertFalse(Asset.all_companies.exists())
        self.client.force_login(self.owner)
        response = self.client.get(reverse('assets:import_template'))
        self.assertEqual(response['Content-Type'], 'text/csv; charset=utf-8')
        self.assertTrue(response.content.decode('utf-8').startswith('﻿name,'))


# ---------------------------------------------------------------------------------------------------- calendar

class CalendarTests(TestCase):
    def setUp(self):
        self.company = make_company('A')
        self.other = make_company('B')
        self.owner = make_user('o@example.com', self.company)
        self.editor = make_user('e@example.com', self.company, Membership.Role.EDITOR)
        Asset.all_companies.create(company=self.company, kind=Asset.DOMAIN, name='Alofoq, trading; "main"', expiry_date=datetime.date(2027, 3, 14),
                                   provider='GoDaddy', identifier='alofoq-trading.com')
        Asset.all_companies.create(company=self.company, kind=Asset.HOSTING, name='No date')
        Asset.all_companies.create(company=self.other, kind=Asset.DOMAIN, name='Secret of B', expiry_date=datetime.date(2027, 4, 1))

    def make_feed(self, user=None):
        self.client.force_login(user or self.owner)
        self.client.post(reverse('assets:calendar'))
        return AssetCalendar.all_companies.get(company=self.company)

    def test_only_managers_make_the_address(self):
        self.client.force_login(self.editor)
        self.client.post(reverse('assets:calendar'))
        self.assertFalse(AssetCalendar.all_companies.exists())
        feed = self.make_feed()
        self.assertGreaterEqual(len(feed.token), 20)

    def test_the_feed_needs_no_login_and_has_only_its_own_companys_dated_assets(self):
        feed = self.make_feed()
        self.client.logout()
        response = self.client.get(reverse('assets_public:feed', args=[feed.token]))
        self.assertEqual(response['Content-Type'], 'text/calendar; charset=utf-8')
        text = response.content.decode('utf-8')
        self.assertTrue(text.startswith('BEGIN:VCALENDAR\r\n') and text.endswith('END:VCALENDAR\r\n'))
        self.assertEqual(text.count('BEGIN:VEVENT'), 1)
        self.assertIn('DTSTART;VALUE=DATE:20270314', text)
        self.assertIn('DTEND;VALUE=DATE:20270315', text)
        self.assertIn('TRIGGER:-P7D', text)
        self.assertNotIn('Secret of B', text)
        self.assertNotIn('No date', text)

    def test_text_is_escaped_and_long_lines_folded(self):
        feed = self.make_feed()
        unfolded = self.client.get(reverse('assets_public:feed', args=[feed.token])).content.decode('utf-8').replace('\r\n ', '')
        self.assertIn('Alofoq\\, trading\\; "main"', unfolded)
        for line in self.client.get(reverse('assets_public:feed', args=[feed.token])).content.split(b'\r\n'):
            self.assertLessEqual(len(line), 75)

    def test_a_new_address_replaces_the_old_one(self):
        old = self.make_feed().token
        self.client.post(reverse('assets:calendar'))
        new = AssetCalendar.all_companies.get(company=self.company).token
        self.assertNotEqual(old, new)
        self.assertEqual(self.client.get(reverse('assets_public:feed', args=[old])).status_code, 404)
        self.assertEqual(self.client.get(reverse('assets_public:feed', args=[new])).status_code, 200)
        self.assertEqual(AssetCalendar.all_companies.count(), 1)

    def test_an_unknown_address_is_not_found(self):
        self.assertEqual(self.client.get(reverse('assets_public:feed', args=['nope'])).status_code, 404)


# ---------------------------------------------------------------------------------------------------- digest

class DigestTests(TestCase):
    def setUp(self):
        self.company = make_company('A')
        self.owner = make_user('o@example.com', self.company)
        self.editor = make_user('e@example.com', self.company, Membership.Role.EDITOR)

    def make(self, **kwargs):
        data = {'company': self.company, 'kind': Asset.DOMAIN, 'name': 'example.com'}
        data.update(kwargs)
        return Asset.all_companies.create(**data)

    def test_managers_get_one_mail_with_late_and_due_assets(self):
        self.make(name='late.com', expiry_date=days(-3))
        self.make(name='soon.com', expiry_date=days(7))
        self.make(name='far.com', expiry_date=days(200))
        mail.outbox.clear()
        self.assertEqual(digest.send_all(), 1)
        self.assertEqual([m.to for m in mail.outbox], [['o@example.com']])         # the editor is not a manager
        body = mail.outbox[0].body
        self.assertIn('late.com', body)
        self.assertIn('soon.com', body)
        self.assertNotIn('far.com', body)
        self.assertIn('/app/assets/?status=soon', body)

    def test_nothing_due_nothing_sent(self):
        self.make(expiry_date=days(200))
        mail.outbox.clear()
        self.assertEqual(digest.send_all(), 0)
        self.assertEqual(mail.outbox, [])

    def test_a_person_who_turned_e_mails_off_gets_none(self):
        self.make(expiry_date=days(2))
        self.owner.email_notifications = False
        self.owner.save()
        mail.outbox.clear()
        self.assertEqual(digest.send_all(), 0)


# ---------------------------------------------------------------------------------------------------- links to the rest of the product

class IntegrationTests(TestCase):
    def setUp(self):
        self.company = make_company('A')
        self.other = make_company('B')
        self.owner = make_user('o@example.com', self.company)
        self.stranger = make_user('s@example.com', self.other)

    def record(self, company, title):
        from apps.library.models import Record
        return Record.all_companies.create(company=company, title=title, file='x/y.pdf', content_type='application/pdf')

    def test_only_the_companys_own_papers_can_be_linked(self):
        mine, theirs = self.record(self.company, 'Invoice'), self.record(self.other, 'Secret')
        self.client.force_login(self.owner)
        page = self.client.get(reverse('assets:new'))
        self.assertEqual(list(page.context['form'].fields['document'].queryset), [mine])
        self.client.post(reverse('assets:new'), {'kind': 'domain', 'name': 'x.com', 'currency': 'USD', 'cycle': 'yearly', 'document': theirs.pk})
        self.assertFalse(Asset.all_companies.exists())
        self.client.post(reverse('assets:new'), {'kind': 'domain', 'name': 'x.com', 'currency': 'USD', 'cycle': 'yearly', 'document': mine.pk})
        self.assertEqual(Asset.all_companies.get().document, mine)

    def test_the_dashboard_and_the_waiting_list_show_due_assets(self):
        from apps.core import attention
        Asset.all_companies.create(company=self.company, kind=Asset.DOMAIN, name='late.com', expiry_date=days(-1))
        Asset.all_companies.create(company=self.company, kind=Asset.DOMAIN, name='far.com', expiry_date=days(300))
        self.client.force_login(self.owner)
        response = self.client.get(reverse('core:dashboard'))
        self.assertEqual((response.context['overview']['assets'], response.context['overview']['assets_due']), (2, 1))
        membership = Membership.objects.get(user=self.owner, company=self.company)
        from apps.core.tenancy import company_context
        with company_context(self.company):
            groups = attention.waiting(self.company, self.owner, membership)
        items = [i for g in groups for i in g['items'] if i['url'].startswith(reverse('assets:list'))]
        self.assertEqual([i['count'] for i in items], [1])

    def test_marid_reads_the_assets_of_the_company_only(self):
        from apps.assistant import views as marid
        from apps.core.tenancy import company_context
        Asset.all_companies.create(company=self.company, kind=Asset.DOMAIN, name='alofoq.com', provider='GoDaddy', expiry_date=days(5), cost=45)
        Asset.all_companies.create(company=self.company, kind=Asset.HOSTING, name='Hosting', expiry_date=days(200), cost=10, cycle=Asset.MONTHLY)
        Asset.all_companies.create(company=self.other, kind=Asset.DOMAIN, name='secret-of-b.com', expiry_date=days(1))
        with company_context(self.company):
            everything = marid._search_assets(None, '', None)
            soon = marid._search_assets(None, '', 30)
            named = marid._search_assets(None, 'godaddy', None)
        self.assertIn('165.00 USD', everything)                 # 45 + 10 * 12
        self.assertIn('alofoq.com', everything)
        self.assertNotIn('secret-of-b.com', everything)
        self.assertIn('alofoq.com', soon)
        self.assertNotIn('Hosting', soon)
        self.assertIn('alofoq.com', named)
        self.assertNotIn('Hosting (', named)
        with company_context(self.other):
            self.assertNotIn('alofoq.com', marid._search_assets(None, '', None))
        self.assertIn('search_assets', [t['function']['name'] for t in marid.TOOLS])
