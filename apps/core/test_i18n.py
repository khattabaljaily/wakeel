from django.core import mail
from django.test import TestCase
from django.urls import reverse
from django.utils import translation

from apps.accounts.models import User
from apps.content.tests import make_company, make_user
from apps.notifications.models import Notification
from apps.notifications.services import notify


class LanguageTests(TestCase):
    def test_arabic_by_default_whatever_the_browser_says(self):
        r = self.client.get(reverse('accounts:login'), HTTP_ACCEPT_LANGUAGE='en-US,en;q=0.9')
        self.assertContains(r, 'lang="ar" dir="rtl"')
        self.assertContains(r, 'مرحباً بعودتك')

    def test_switch_before_and_after_signing_in(self):
        r = self.client.post(reverse('core:set_language'), {'language': 'en', 'next': reverse('accounts:login')})
        self.assertRedirects(r, reverse('accounts:login'), fetch_redirect_response=False)
        page = self.client.get(reverse('accounts:login'))
        self.assertContains(page, 'lang="en" dir="ltr"')
        self.assertContains(page, 'Welcome back')
        self.assertContains(page, 'bootstrap.min.css')

        company = make_company()
        user = make_user('u@x.test', company)
        self.client.force_login(user)
        self.client.post(reverse('core:set_language'), {'language': 'en'})
        user.refresh_from_db()
        self.assertEqual(user.language, 'en')
        self.client.cookies.clear()
        self.client.force_login(user)  # the account remembers it, without the cookie
        self.assertContains(self.client.get(reverse('core:dashboard')), 'Upcoming posts')

    def test_unsafe_next_is_ignored(self):
        r = self.client.post(reverse('core:set_language'), {'language': 'en', 'next': 'https://evil.example/'})
        self.assertEqual(r['Location'], '/')

    def test_each_recipient_reads_notifications_in_their_language(self):
        company = make_company()
        ar_user = make_user('ar@x.test', company)
        en_user = make_user('en@x.test', company)
        en_user.language = 'en'
        en_user.save()
        from apps.content.events import plan_ready
        from apps.content.models import ContentPlan
        import datetime
        plan = ContentPlan.objects.create(company=company, month=datetime.date(2026, 10, 1), platforms=['facebook'],
                                          title='', created_by=ar_user)
        with translation.override('ar'):
            plan_ready(plan, 5)
        self.assertIn('جاهزة', Notification.objects.get(user=ar_user).message)
        self.assertIn('is ready', Notification.objects.get(user=en_user).message)
        subjects = {m.to[0]: m.body for m in mail.outbox}
        self.assertIn('Hello', subjects['en@x.test'])
        self.assertIn('مرحباً', subjects['ar@x.test'])


class TwoLanguagesTests(TestCase):
    """The screens come in Arabic and English only (owner's decision, 2026-11-25)."""
    CODES = ['ar', 'en']
    DROPPED = ['tr', 'de', 'fr', 'es', 'pt', 'it', 'ru', 'zh-hans', 'ja', 'ko', 'hi', 'id', 'fa', 'am']

    def test_the_menu_lists_only_these(self):
        page = self.client.get(reverse('accounts:login')).content.decode()
        for code in self.CODES:
            self.assertIn(f'name="language" value="{code}"', page, code)
        for code in self.DROPPED:
            self.assertNotIn(f'name="language" value="{code}"', page, code)

    def test_a_dropped_language_cannot_be_picked_and_a_saved_one_reads_arabic(self):
        user = make_user('d@x.test', make_company())
        self.client.force_login(user)
        self.client.post(reverse('core:set_language'), {'language': 'fr'})
        user.refresh_from_db()
        self.assertNotEqual(user.language, 'fr')
        user.language = 'fr'                                                    # saved before the cut
        user.save(update_fields=['language'])
        self.assertContains(self.client.get(reverse('core:dashboard')), 'lang="ar"')

    def test_every_language_can_be_picked_and_saved_on_the_account(self):
        user = make_user('u@x.test', make_company())
        self.client.force_login(user)
        for code in self.CODES:
            self.client.post(reverse('core:set_language'), {'language': code})
            user.refresh_from_db()
            self.assertEqual(user.language, code)
            page = self.client.get(reverse('core:dashboard'))
            self.assertEqual(page.status_code, 200)
            self.assertContains(page, f'lang="{code}"')

    def test_direction_follows_the_language(self):
        for code, rtl in (('ar', True), ('en', False)):
            self.client.post(reverse('core:set_language'), {'language': code})
            page = self.client.get(reverse('accounts:login'))
            self.assertContains(page, f'lang="{code}" dir="{"rtl" if rtl else "ltr"}"')
