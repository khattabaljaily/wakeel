import io
import shutil
import tempfile
import datetime

from django.core import mail
from django.core.files.uploadedfile import SimpleUploadedFile
from django.test import TestCase, override_settings
from django.urls import reverse
from PIL import Image

from apps.content.models import ContentPlan
from apps.content.tests import make_company, make_user

from .models import Agency, Membership

MEDIA = tempfile.mkdtemp()


def png():
    buf = io.BytesIO()
    Image.new('RGB', (4, 4), '#123456').save(buf, 'PNG')
    return SimpleUploadedFile('logo.png', buf.getvalue(), 'image/png')


@override_settings(MEDIA_ROOT=MEDIA)
class AgencyTests(TestCase):
    @classmethod
    def tearDownClass(cls):
        super().tearDownClass()
        shutil.rmtree(MEDIA, ignore_errors=True)

    def setUp(self):
        self.user = make_user('agency@example.com')
        self.mine = make_company('عميل أ')
        self.other = make_company('عميل ب')
        Membership.objects.create(company=self.mine, user=self.user, role=Membership.Role.OWNER)
        Membership.objects.create(company=self.other, user=self.user, role=Membership.Role.EDITOR)  # not an owner here
        self.client.force_login(self.user)

    def save(self, companies, **extra):
        return self.client.post(reverse('companies:agency'), {'name': 'وكالة النجم', 'color': '#ff0000', 'website': 'star.example',
                                                              'logo': png(), 'companies': companies, **extra})

    def test_owner_attaches_only_companies_they_own(self):
        self.save([self.mine.pk, self.other.pk])
        agency = Agency.objects.get(owner=self.user)
        self.mine.refresh_from_db()
        self.other.refresh_from_db()
        self.assertEqual((self.mine.agency, self.other.agency), (agency, None))
        self.save([])  # unticked: back to Wakeel's brand
        self.mine.refresh_from_db()
        self.assertIsNone(self.mine.agency)

    def test_client_review_page_and_email_show_the_agency(self):
        self.save([self.mine.pk])
        plan = ContentPlan.objects.create(company=self.mine, month=datetime.date(2026, 11, 1), platforms=['facebook'],
                                          status=ContentPlan.Status.READY, share_token='tok123')
        self.client.logout()
        page = self.client.get(reverse('review:plan', args=['tok123'])).content.decode()
        self.assertIn('وكالة النجم', page)
        self.assertNotIn('بواسطة وكيل', page)
        self.mine.refresh_from_db()
        self.mine.autopilot_client_email = 'client@example.com'
        self.mine.save()
        from apps.content.autopilot import deliver
        deliver(plan)
        self.assertIn('وكالة النجم', mail.outbox[0].body)
        self.assertNotIn('عبر وكيل', mail.outbox[0].body)

    def test_turning_off_restores_wakeel(self):
        self.save([self.mine.pk])
        self.client.post(reverse('companies:agency'), {'action': 'off'})
        self.assertFalse(Agency.objects.exists())
        self.mine.refresh_from_db()
        self.assertIsNone(self.mine.agency)
