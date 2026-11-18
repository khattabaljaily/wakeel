import io
import shutil
import tempfile
from pathlib import Path

from django.core.files.uploadedfile import SimpleUploadedFile
from django.test import TestCase, override_settings
from django.urls import reverse
from PIL import Image, ImageDraw

from apps.accounts.models import User
from apps.companies.models import Company, Membership
from apps.core import filecrypto
from apps.core.tenancy import company_context

from . import letterheads, safearea
from .models import LetterheadVariant


def letterhead_png(name='lh.png'):
    """A page with a blue header block and a blue footer block."""
    im = Image.new('RGB', (794, 1123), 'white')
    d = ImageDraw.Draw(im)
    d.rectangle([60, 40, 734, 130], fill=(30, 60, 140))
    d.rectangle([60, 1030, 734, 1080], fill=(30, 60, 140))
    buf = io.BytesIO()
    im.save(buf, 'PNG')
    return SimpleUploadedFile(name, buf.getvalue(), content_type='image/png')


class Base(TestCase):
    def setUp(self):
        self.company = Company.objects.create(name='Alpha', industry='x', country='Qatar', main_language='ar')
        self.owner = self.member('owner@example.com', 'owner')
        self.editor = self.member('editor@example.com', 'editor')
        self.client.force_login(self.owner)
        self.client.cookies['wakeel_lang'] = 'en'

    def member(self, email, role, company=None):
        user = User.objects.create_user(email, email, 'a-Strong-pass-77')
        Membership.objects.create(company=company or self.company, user=user, role=role)
        return user


class LetterheadTests(Base):
    def add(self, language='ar', upload=None):
        return self.client.post(reverse('identity:letterhead_add'), {'language': language, 'file': upload or letterhead_png()})

    def test_the_main_language_letterhead_lives_on_the_company_and_is_encrypted(self):
        self.assertRedirects(self.add('ar'), reverse('identity:letterheads'))
        self.company.refresh_from_db()
        self.assertEqual(self.company.asset_sources['letterhead'], 'uploaded')
        path = Path(self.company.letterhead.storage.path(self.company.letterhead.name))
        self.assertTrue(self.company.letterhead.name.startswith(f'{self.company.pk}/'))
        self.assertTrue(filecrypto.is_encrypted(path.read_bytes()))
        page = self.client.get(reverse('identity:letterheads')).content.decode()
        self.assertIn(reverse('identity:letterhead_main'), page)
        served = self.client.get(reverse('identity:letterhead_main'))
        self.assertEqual(served.status_code, 200)
        self.assertEqual(served['Cache-Control'], 'private, no-store')
        self.assertEqual(Image.open(io.BytesIO(b''.join(served.streaming_content))).size, (794, 1123))     # decrypted on the way out

    def test_another_language_is_a_variant_and_replacing_it_keeps_one_row(self):
        self.add('en')
        self.add('en')
        self.assertEqual(LetterheadVariant.all_companies.filter(company=self.company, language='en').count(), 1)
        self.assertEqual(self.client.get(reverse('identity:letterhead_file', args=['en'])).status_code, 200)
        self.assertEqual(self.client.get(reverse('identity:letterhead_file', args=['de'])).status_code, 404)

    def test_a_document_uses_the_letterhead_of_its_language_else_the_main_one(self):
        self.add('ar')
        self.add('en')
        company = Company.objects.get(pk=self.company.pk)
        self.assertEqual(letterheads.for_document(company, 'en')['language'], 'en')
        found = letterheads.for_document(company, 'fr')
        self.assertEqual((found['language'], found['exact']), ('ar', False))        # falls back to the main one
        self.assertIsNone(letterheads.for_document(Company.objects.create(name='B', industry='x', country='Qatar'), 'ar'))

    def test_the_text_area_is_found_from_the_image(self):
        self.add('ar')
        top, bottom = safearea.margins(Company.objects.get(pk=self.company.pk).letterhead)
        self.assertTrue(14 <= top <= 120 and 14 <= bottom <= 80)
        self.assertGreater(top, 30)                       # below the header block (about 50 mm tall with its gap)
        self.assertGreater(bottom, 25)

    def test_only_managers_change_letterheads_and_members_of_other_companies_cannot_read_them(self):
        self.add('en')
        self.client.force_login(self.editor)
        self.assertEqual(self.add('de').status_code, 403)
        self.assertFalse(LetterheadVariant.all_companies.filter(language='de').exists())
        self.assertEqual(self.client.get(reverse('identity:letterheads')).status_code, 200)       # members see them
        beta = Company.objects.create(name='Beta', industry='x', country='Qatar')
        stranger = self.member('s@example.com', 'owner', beta)
        self.client.force_login(stranger)
        self.assertEqual(self.client.get(reverse('identity:letterhead_file', args=['en'])).status_code, 404)

    def test_delete_removes_the_row_and_the_file(self):
        self.add('en')
        variant = LetterheadVariant.all_companies.get(company=self.company, language='en')
        path = Path(variant.file.storage.path(variant.file.name))
        self.assertTrue(path.exists())
        self.client.post(reverse('identity:letterhead_delete', args=['en']))
        self.assertFalse(LetterheadVariant.all_companies.exists())
        self.assertFalse(path.exists())
        self.add('ar')
        self.client.post(reverse('identity:letterhead_delete', args=['ar']))
        self.company.refresh_from_db()
        self.assertFalse(self.company.letterhead)

    def test_a_file_that_is_not_an_image_is_refused(self):
        self.add('ar', SimpleUploadedFile('x.png', b'not an image', content_type='image/png'))
        self.company.refresh_from_db()
        self.assertFalse(self.company.letterhead)

    def test_a_pdf_becomes_its_first_page(self):
        import io as _io
        from pypdf import PdfWriter
        writer = PdfWriter()
        writer.add_blank_page(width=595, height=842)
        buf = _io.BytesIO()
        writer.write(buf)
        self.add('ar', SimpleUploadedFile('lh.pdf', buf.getvalue(), content_type='application/pdf'))
        self.company.refresh_from_db()
        self.assertTrue(self.company.letterhead)
        with company_context(self.company):
            image = Image.open(self.company.letterhead.open('rb'))
        self.assertEqual(max(image.size), 1754)


class OfficialDetailsTests(Base):
    def post_brand(self, **extra):
        data = {'name': 'Alpha', 'industry': 'x', 'country': 'Qatar', 'timezone': 'Asia/Qatar', 'description': 'd',
                'content_language': 'ar_msa', 'tone': 'professional', 'primary_color': '#4f46e5', 'secondary_color': '#0ea5e9',
                'accent_color': '#f59e0b', 'heading_font': 'cairo', 'body_font': 'cairo', 'main_language': 'ar', **extra}
        return self.client.post(reverse('companies:brand'), data)

    def test_the_official_details_are_saved_on_the_company(self):
        self.post_brand(legal_name='Alpha W.L.L.', address='Doha, West Bay', cr_number='12345', tax_number='T-9',
                        official_email='info@alpha.test', documents_need_approval='on')
        c = Company.objects.get(pk=self.company.pk)
        self.assertEqual((c.legal_name, c.address, c.cr_number, c.tax_number, c.official_email, c.documents_need_approval),
                         ('Alpha W.L.L.', 'Doha, West Bay', '12345', 'T-9', 'info@alpha.test', True))

    def test_the_name_and_address_in_other_languages_are_kept_per_language(self):
        self.post_brand(address='الدوحة', other_lang=['en', 'de', 'fr'], other_name=['Alpha Co', '', ''],
                        other_address=['Doha, West Bay', '', ''])
        c = Company.objects.get(pk=self.company.pk)
        self.assertEqual(c.other_names, {'en': {'name': 'Alpha Co', 'address': 'Doha, West Bay'}})     # empty rows are dropped
        self.assertEqual((c.name_for('en'), c.address_for('en')), ('Alpha Co', 'Doha, West Bay'))
        self.assertEqual((c.name_for('de'), c.address_for('de')), ('Alpha', 'الدوحة'))               # no entry: the main language

    def test_the_same_language_twice_or_the_main_language_is_refused(self):
        r = self.post_brand(other_lang=['en', 'en'], other_name=['A', 'B'], other_address=['', ''])
        self.assertEqual(r.status_code, 200)
        self.assertEqual(Company.objects.get(pk=self.company.pk).other_names, {})
        r = self.post_brand(other_lang=['ar'], other_name=['A'], other_address=[''])
        self.assertEqual(r.status_code, 200)

    def test_the_form_shows_the_official_step_and_the_saved_other_names(self):
        Company.objects.filter(pk=self.company.pk).update(other_names={'en': {'name': 'Alpha Co'}})
        page = self.client.get(reverse('companies:brand')).content.decode()
        self.assertIn('data-pane="5"', page)
        self.assertIn('value="Alpha Co"', page)
        self.assertIn(reverse('identity:letterheads'), page)

    def test_the_website_autofill_also_returns_the_official_name_address_and_email(self):
        from unittest import mock

        from apps.ai.client import AIResult
        site = {'url': 'https://alpha.test', 'title': 't', 'description': 'd', 'text': 'x' * 400, 'logo_url': '', 'colors': [],
                'contacts': {'phone': '+97455551234', 'official_email': 'info@alpha.test'}}
        data = {'name': 'Alpha', 'legal_name': 'Alpha W.L.L.', 'address': 'Doha, West Bay', 'industry': 'تقنية', 'country': 'قطر',
                'city': 'الدوحة', 'description': 'د', 'products': '', 'usp': '', 'target_audience': '', 'goals': '', 'voice_notes': '',
                'dos': '', 'donts': '', 'brand_hashtags': '', 'tone': 'professional', 'content_language': 'ar_msa'}
        with mock.patch('apps.companies.views.read_site', return_value=site), \
                mock.patch('apps.companies.views.look_at', return_value={'logo_png': None, 'colors': []}), \
                mock.patch('apps.companies.views.draft_brand', return_value=AIResult(data=data)):
            r = self.client.post(reverse('companies:autofill'), {'url': 'https://alpha.test'}, content_type='application/json')
        fields = r.json()['fields']
        self.assertEqual((fields['legal_name'], fields['address'], fields['official_email']),
                         ('Alpha W.L.L.', 'Doha, West Bay', 'info@alpha.test'))
