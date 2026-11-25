"""Facebook/Instagram connect is "coming soon" while Meta reviews the app; TikTok stays open."""
from django.test import TestCase, override_settings
from django.urls import reverse

from apps.content.tests import make_company, make_user


@override_settings(META_ENABLED=True, META_PUBLIC=False, META_PREVIEW_EMAILS=['tester@x.test'], TIKTOK_ENABLED=True)
class MetaGateTests(TestCase):
    def setUp(self):
        self.company = make_company('شركة')
        self.owner = make_user('o@x.test', self.company)
        self.client.force_login(self.owner)
        self.client.cookies['wakeel_lang'] = 'ar'

    def test_an_ordinary_owner_sees_coming_soon_and_cannot_start_the_flow(self):
        page = self.client.get(reverse('social:accounts'))
        self.assertContains(page, 'النشر على فيسبوك وإنستغرام والنشر التلقائي قريباً')
        self.assertNotContains(page, 'قيد الاعتماد')                      # no details about why: only that it is coming soon
        self.assertContains(page, 'قريباً</span>')
        for response in (self.client.get(reverse('social:setup')),
                         self.client.post(reverse('social:meta_connect')),
                         self.client.get(reverse('social:meta_callback'), {'code': 'x', 'state': 'y'})):
            self.assertRedirects(response, reverse('social:accounts'), fetch_redirect_response=False)
        self.assertNotIn('facebook.com', self.client.post(reverse('social:meta_connect')).get('Location', ''))

    def test_the_autopilot_page_says_auto_publishing_is_coming_soon_only_while_closed(self):
        self.assertContains(self.client.get(reverse('companies:autopilot')), 'النشر التلقائي على فيسبوك وإنستغرام.')
        with self.settings(META_PUBLIC=True):
            self.assertNotContains(self.client.get(reverse('companies:autopilot')), 'النشر التلقائي على فيسبوك وإنستغرام.')

    def test_tiktok_stays_open(self):
        self.assertEqual(self.client.get(reverse('social:setup'), {'step': 'tiktok'}).status_code, 200)

    def test_testers_admins_and_everyone_after_approval(self):
        tester = make_user('Tester@x.test', self.company)
        self.client.force_login(tester)
        self.assertEqual(self.client.get(reverse('social:setup')).status_code, 200)
        self.assertNotContains(self.client.get(reverse('social:accounts')), 'والنشر التلقائي قريباً')
        self.client.force_login(self.owner)
        with self.settings(META_PUBLIC=True):
            self.assertEqual(self.client.get(reverse('social:setup')).status_code, 200)
