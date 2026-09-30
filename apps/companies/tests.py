from django.test import TestCase
from django.urls import reverse

from apps.accounts.models import User

from .models import Company, Membership


class OnboardingTests(TestCase):
    def test_sign_up_waits_for_approval_then_adds_companies_with_the_wizard(self):
        from django.core import mail
        admin = User.objects.create_superuser(username='root', email='root@x.test', password='Strong-pass-123')
        r = self.client.post(reverse('accounts:register'), {
            'first_name': 'خطاب', 'email': 'k@x.test', 'password': 'Strong-pass-123', 'phone': '+249 912 345 678'})
        self.assertRedirects(r, reverse('accounts:pending'))
        user = User.objects.get(email='k@x.test')
        self.assertFalse(user.is_approved)
        self.assertFalse(Company.objects.exists())  # sign-up is about the person only
        self.assertEqual([m.to for m in mail.outbox], [['root@x.test']])
        # Until approved, the app, the wizard and the API all lead to the waiting page.
        for name in ('core:dashboard', 'companies:create', 'content:plan_list'):
            self.assertRedirects(self.client.get(reverse(name)), reverse('accounts:pending'), fetch_redirect_response=False)
        self.assertEqual(self.client.get('/api/jobs/1/').status_code, 403)
        self.assertContains(self.client.get(reverse('accounts:pending')), 'حسابك قيد المراجعة')

        # A system admin approves the account from the console; the user is emailed.
        mail.outbox.clear()
        self.client.force_login(admin)
        self.assertContains(self.client.get(reverse('ops:signups')), 'k@x.test')
        self.client.post(reverse('ops:signup_approve', args=[user.pk]))
        user.refresh_from_db()
        self.assertTrue(user.is_approved)
        self.assertEqual([m.to for m in mail.outbox], [['k@x.test']])

        # Then the user adds a company through the wizard, and it's ready at once.
        self.client.force_login(user)
        self.assertRedirects(self.client.get(reverse('core:dashboard')), reverse('companies:create'))
        r = self.client.post(reverse('companies:create'), {
            'name': 'إنجاز', 'industry': 'برمجيات', 'country': 'السودان', 'timezone': 'Africa/Khartoum',
            'description': 'حلول', 'content_language': 'ar_msa', 'tone': 'professional',
            'primary_color': '#1E3A8A', 'secondary_color': '#0EA5E9', 'accent_color': '#F6A821',
            'heading_font': 'cairo', 'body_font': 'tajawal',
        })
        self.assertRedirects(r, reverse('content:plan_create'))
        company = Company.objects.get(name='إنجاز')
        self.assertTrue(company.is_usable)
        self.assertEqual(Membership.objects.get(company=company, user=user).role, Membership.Role.OWNER)
        self.assertEqual(self.client.get(reverse('core:dashboard')).status_code, 200)

    def test_admin_rejects_a_sign_up(self):
        admin = User.objects.create_superuser(username='root', email='root@x.test', password='Strong-pass-123')
        self.client.post(reverse('accounts:register'), {'first_name': 'س', 'email': 's@x.test', 'password': 'Strong-pass-123'})
        user = User.objects.get(email='s@x.test')
        self.client.force_login(admin)
        self.client.post(reverse('ops:signup_reject', args=[user.pk]))
        self.assertFalse(User.objects.filter(email='s@x.test').exists())

    def test_login_with_email(self):
        User.objects.create_user(username='someone', email='s@x.test', password='Strong-pass-123')
        r = self.client.post(reverse('accounts:login'), {'username': 's@x.test', 'password': 'Strong-pass-123'})
        self.assertEqual(r.status_code, 302)


from unittest import mock  # noqa: E402

from apps.ai.client import AIResult  # noqa: E402

from .scrape import FetchError, read_site, safe_get  # noqa: E402

HOME = b'''<html><head><title>Nile Tech</title><meta name="description" content="Software for Sudanese businesses">
<meta name="theme-color" content="#1E3A8A"><link rel="stylesheet" href="/app.css"><style>.x{color:#ffffff}</style></head>
<body><img src="/img/logo.png" alt="Nile Tech logo"><script>var secret = 1;</script>
<h1>We build ERP systems</h1><p>''' + b'Trusted software. ' * 30 + b'''</p>
<a href="/about-us">About</a><a href="https://facebook.com/niletech">fb</a><a href="https://instagram.com/niletech/">ig</a>
<a href="tel:+249912345678">call</a><a href="https://wa.me/249912345678">wa</a><a href="https://other.com/about">x</a></body></html>'''
ABOUT = b'<html><body><h2>About us</h2><p>Founded in Khartoum.</p></body></html>'
CSS = b'.btn{background:#F6A821}.a{color:#f6a821}.b{color:#0EA5E9}.c{color:#333333}'


def fake_get(url, **kwargs):
    pages = {'https://nile.test': ('text/html', HOME), 'https://nile.test/about-us': ('text/html', ABOUT),
             'https://nile.test/app.css': ('text/css', CSS)}
    ctype, body = pages[url.rstrip('/')]
    return url, ctype, body


class ReadSiteTests(TestCase):
    @mock.patch('apps.companies.scrape.safe_get', side_effect=fake_get)
    def test_extracts_text_contacts_colors_logo(self, _):
        site = read_site('nile.test')
        self.assertIn('We build ERP systems', site['text'])
        self.assertIn('Founded in Khartoum', site['text'])
        self.assertNotIn('secret', site['text'])
        self.assertEqual(site['logo_url'], 'https://nile.test/img/logo.png')
        self.assertEqual(site['colors'][0], '#1e3a8a')          # theme-color first
        self.assertIn('#f6a821', site['colors'])                # most used colour in the CSS
        self.assertEqual(site['contacts']['instagram_handle'], 'niletech')
        self.assertEqual(site['contacts']['phone'], '+249912345678')
        self.assertEqual(site['contacts']['whatsapp'], '+249912345678')

    def test_blocks_private_addresses(self):
        for url in ('http://127.0.0.1/', 'http://localhost:8000/', 'http://169.254.169.254/latest/', 'file:///etc/passwd'):
            with self.assertRaises(FetchError, msg=url):
                safe_get(url)


class AutofillViewTests(TestCase):
    def setUp(self):
        self.user = User.objects.create_user(username='u@x.test', email='u@x.test', password='Strong-pass-123')
        self.client.force_login(self.user)

    @mock.patch('apps.companies.views.look_at', return_value={'colors': [], 'logo_png': None})
    @mock.patch('apps.companies.views.draft_brand')
    @mock.patch('apps.companies.scrape.safe_get', side_effect=fake_get)
    def test_returns_clean_fields(self, _, draft, __):
        draft.return_value = AIResult(data={'name': 'نايل تك', 'industry': 'برمجيات', 'tone': 'sarcastic',
                                            'content_language': 'ar_msa', 'city': ''})
        r = self.client.post(reverse('companies:autofill'), {'url': 'https://nile.test'}, content_type='application/json')
        self.assertEqual(r.status_code, 200)
        data = r.json()
        self.assertEqual(data['fields']['name'], 'نايل تك')
        self.assertNotIn('tone', data['fields'])      # invalid enum dropped
        self.assertNotIn('city', data['fields'])      # empty dropped
        self.assertEqual(data['fields']['website'], 'https://nile.test')
        self.assertEqual(data['logo_url'], 'https://nile.test/img/logo.png')

    def test_bad_url_is_reported(self):
        r = self.client.post(reverse('companies:autofill'), {'url': 'http://127.0.0.1'}, content_type='application/json')
        self.assertEqual(r.status_code, 400)
        self.assertIn('error', r.json())


from .visual import pick_palette  # noqa: E402


class PaletteTests(TestCase):
    def test_logo_colours_lead_and_noise_is_dropped(self):
        page = {'#ffffff': 5000, '#0f1414': 3000, '#1e40af': 400, '#1d4ed8': 300, '#ff5f57': 2}
        self.assertEqual(pick_palette(page, {'#cca830': 1.0}), ['#cca830', '#0f1414', '#1e40af'])

    def test_light_site_without_logo(self):
        self.assertEqual(pick_palette({'#ffffff': 9000, '#00a0e1': 500, '#009137': 200}), ['#00a0e1', '#009137'])


class CapturedLogoTests(TestCase):
    @mock.patch('apps.companies.views.look_at')
    @mock.patch('apps.companies.views.draft_brand')
    @mock.patch('apps.companies.scrape.safe_get', side_effect=fake_get)
    def test_captured_logo_is_saved_with_company(self, _, draft, look):
        import io
        from PIL import Image
        buf = io.BytesIO()
        Image.new('RGBA', (8, 8), (204, 168, 48, 255)).save(buf, 'PNG')
        look.return_value = {'colors': ['#cca830', '#0f1414'], 'logo_png': buf.getvalue()}
        draft.return_value = AIResult(data={'name': 'نايل'})
        user = User.objects.create_user(username='l@x.test', email='l@x.test', password='Strong-pass-123')
        self.client.force_login(user)
        data = self.client.post(reverse('companies:autofill'), {'url': 'https://nile.test'}, content_type='application/json').json()
        self.assertEqual(data['colors'], ['#cca830', '#0f1414'])
        self.assertIn('/tmp/autofill/', data['logo_url'])
        self.client.post(reverse('companies:create'), {
            'name': 'نايل', 'industry': 'x', 'country': 'y', 'timezone': 'Asia/Qatar', 'description': 'z',
            'content_language': 'ar_msa', 'tone': 'professional', 'primary_color': '#cca830',
            'secondary_color': '#0f1414', 'accent_color': '#f59e0b', 'heading_font': 'cairo', 'body_font': 'tajawal',
            'logo_url': data['logo_url'],
        })
        company = Company.objects.get(name='نايل')
        self.assertTrue(company.logo)
        company.logo.delete(save=False)


from .views import guess_timezone  # noqa: E402


class TimezoneGuessTests(TestCase):
    def test_from_country_then_phone(self):
        self.assertEqual(guess_timezone('السودان', []), 'Africa/Khartoum')
        self.assertEqual(guess_timezone('State of Qatar', []), 'Asia/Qatar')
        self.assertEqual(guess_timezone('', ['+249 912 345 678']), 'Africa/Khartoum')
        self.assertEqual(guess_timezone('', ['00974 5555 1234']), 'Asia/Qatar')
        self.assertEqual(guess_timezone('', ['0912345678']), '')

