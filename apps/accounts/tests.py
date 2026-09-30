import re

from django.core import mail
from django.test import TestCase, override_settings
from django.urls import reverse

from .models import User


@override_settings(SITE_URL='https://app.wakeel.example')
class PasswordResetTests(TestCase):
    def setUp(self):
        self.user = User.objects.create_user(username='a@x.com', email='a@x.com', password='OldPass123!x', first_name='أحمد')

    def test_full_reset_flow(self):
        response = self.client.post(reverse('accounts:password_reset'), {'email': 'A@x.com'})
        self.assertRedirects(response, reverse('accounts:password_reset_done'))
        self.assertEqual(len(mail.outbox), 1)
        body = mail.outbox[0].body
        self.assertIn('أحمد', body)
        link = re.search(r'https://app\.wakeel\.example(/accounts/password/reset/\S+/)', body).group(1)

        # Django swaps the token for a session marker and redirects to the "set-password" URL.
        form_url = self.client.get(link, follow=True).redirect_chain[-1][0]
        response = self.client.post(form_url, {'new_password1': 'NewPass456!y', 'new_password2': 'NewPass456!y'})
        self.assertRedirects(response, reverse('accounts:password_reset_complete'))
        self.user.refresh_from_db()
        self.assertTrue(self.user.check_password('NewPass456!y'))

    def test_unknown_email_sends_nothing_but_looks_the_same(self):
        response = self.client.post(reverse('accounts:password_reset'), {'email': 'nobody@x.com'})
        self.assertRedirects(response, reverse('accounts:password_reset_done'))
        self.assertEqual(len(mail.outbox), 0)

    def test_login_page_links_to_reset(self):
        self.assertContains(self.client.get(reverse('accounts:login')), reverse('accounts:password_reset'))
