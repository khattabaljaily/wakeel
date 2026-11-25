"""The brand studio: price shown = price charged (per element, tier and kit discount), refunds, choosing the logo, isolation."""
import io
from decimal import Decimal
from unittest import mock

from django.test import TestCase
from django.urls import reverse
from PIL import Image

from apps.companies.models import Membership
from apps.content.tests import make_company, make_user
from apps.credits.models import Wallet
from apps.jobs.models import Job
from apps.jobs.runner import run_job

from . import service
from .models import BrandAsset, BrandFile, BrandKit


def png(color='white'):
    out = io.BytesIO()
    Image.new('RGB', (30, 20), color).save(out, 'PNG')
    return out.getvalue()


LOGO_RESULT = {
    'ok': True, 'files': {'c1_preview-on-white.png': png(), 'c1_logo-horizontal.png': png('red'), 'c2_preview-on-white.png': png()},
    'concepts': [{'n': 1, 'name': 'Orbit', 'idea': 'round', 'symbol': '<svg viewBox="0 0 1 1"/>'},
                 {'n': 2, 'name': 'Arrow', 'idea': 'forward', 'symbol': '<svg viewBox="0 0 2 2"/>'}],
    'palette': {'primary': '#112233', 'secondary': '#445566', 'accent': '#778899'}, 'pairing': 'modern', 'keywords': ['bold'],
    'personality': 'Confident.'}


class Base(TestCase):
    def setUp(self):
        self.company = make_company('Alpha')
        self.other = make_company('Beta')
        self.owner = make_user('o@example.com', self.company)
        self.viewer = make_user('v@example.com', self.company, Membership.Role.VIEWER)
        self.stranger = make_user('s@example.com', self.other)
        self.client.force_login(self.owner)

    def balance(self):
        return Wallet.objects.get(company=self.company).balance

    def create(self, element='colors', tier='standard', shown=None, **extra):
        data = {'tier': tier, 'expected_points': service.quote(element, tier).total if shown is None else shown}
        data.update(extra)
        return self.client.post(reverse('brand:create', args=[element]), data)

    def work(self, build):
        job = Job.objects.order_by('-pk').first()
        with mock.patch('apps.brand.service.brand.build', return_value=build):
            run_job(job)
        job.refresh_from_db()
        return job


class PriceTests(Base):
    def test_the_studio_shows_the_points_each_option_will_charge(self):
        page = self.client.get(reverse('brand:studio'))
        self.assertContains(page, f'data-points="{service.quote("logo", "premium").total}"')
        self.assertContains(page, f'data-points="{service.quote("colors", "standard").total}"')

    def test_every_element_in_every_tier_is_charged_exactly_what_is_shown(self):
        BrandKit.all_companies.create(company=self.company, symbol='<svg viewBox="0 0 1 1"/>')          # unlocks the dependent pieces
        for element in service.ELEMENTS:
            for tier in ('standard', 'premium'):
                with self.subTest(element=element, tier=tier):
                    Job.objects.all().delete()
                    BrandAsset.all_companies.all().delete()
                    before = self.balance()
                    shown = service.quote(element, tier)
                    self.create(element, tier)
                    self.assertEqual(before - self.balance(), shown.total)
                    self.assertEqual(Job.objects.get().charge_txn.delta, -shown.total)
                    Wallet.objects.filter(company=self.company).update(balance=before)

    def test_the_owner_prices_are_the_ones_charged(self):
        self.assertEqual(service.quote('logo', 'standard').total, 11000)                        # $3 at 3.64, rounded up
        self.assertEqual(service.quote('logo', 'premium').total, 44000)
        self.assertEqual(service.quote('logo', 'standard', bundle=True).total, 9000)           # 20% off inside the kit: 8.8, rounded up

    def test_a_wrong_price_is_refused_without_charging_or_keeping_an_asset(self):
        before = self.balance()
        self.create('colors', shown=1)
        self.assertEqual((self.balance(), Job.objects.count(), BrandAsset.all_companies.count()), (before, 0, 0))

    def test_not_enough_balance_keeps_nothing(self):
        Wallet.objects.filter(company=self.company).update(balance=0)
        self.create('colors')
        self.assertEqual((Job.objects.count(), BrandAsset.all_companies.count()), (0, 0))

    def test_logo_versions_need_the_logo_first_and_a_name_is_needed(self):
        before = self.balance()
        self.create('logo_variants')
        self.assertEqual((self.balance(), Job.objects.count()), (before, 0))
        self.company.name = ''
        self.company.save()
        self.create('colors')
        self.assertEqual(Job.objects.count(), 0)

    def test_viewers_cannot_build(self):
        self.client.force_login(self.viewer)
        before = self.balance()
        self.create('colors')
        self.assertEqual((Job.objects.count(), self.balance()), (0, before))


class RunTests(Base):
    def test_a_finished_design_keeps_its_files_and_charges_once(self):
        self.create('colors')
        job = self.work({'ok': True, 'files': {'colors.png': png(), 'colors.json': b'{}'}})
        asset = BrandAsset.all_companies.get()
        self.assertEqual((job.status, asset.status, sorted(BrandFile.all_companies.filter(asset=asset).values_list('name', flat=True))), (Job.Status.DONE, BrandAsset.DONE, ['colors.json', 'colors.png']))
        self.assertEqual(job.params['result_url'], reverse('brand:detail', args=[asset.pk]))

    def test_a_failed_design_is_refunded_and_keeps_no_files(self):
        before = self.balance()
        self.create('colors')
        job = self.work({'ok': False, 'code': 'x'})
        self.assertEqual((job.status, BrandAsset.all_companies.get().status, self.balance()), (Job.Status.FAILED, BrandAsset.FAILED, before))
        self.assertEqual(BrandFile.all_companies.count(), 0)

    def test_the_logo_uses_the_ai_chat_and_counts_its_tokens(self):
        self.create('logo', 'premium', note='bold')
        from apps.ai import client as ai
        with mock.patch('apps.docops.ops.client.complete_text', return_value=ai.AIResult({'text': 'x'}, 100, 50, 0, 'claude-opus-5-5')):
            def build(element, tier, data, chat, **options):
                chat('s', 'u', task='logo')               # the logo is the one element that asks the model
                self.assertEqual((data['name'], options['note']), ('Alpha', 'bold'))
                return LOGO_RESULT
            with mock.patch('apps.brand.service.brand.build', side_effect=build):
                job = Job.objects.get()
                run_job(job)
        job.refresh_from_db()
        self.assertEqual((job.status, job.input_tokens), (Job.Status.DONE, 100))

    def test_choosing_a_concept_sets_the_kit_the_logo_and_the_colours(self):
        self.create('logo', 'standard')
        self.work(LOGO_RESULT)
        asset = BrandAsset.all_companies.get()
        self.client.post(reverse('brand:choose', args=[asset.pk, 2]))
        kit = BrandKit.all_companies.get()
        self.assertEqual((kit.chosen_name, kit.palette['primary']), ('Arrow', '#112233'))
        self.company.refresh_from_db()
        self.assertEqual(self.company.primary_color, '#112233')
        self.client.post(reverse('brand:choose', args=[asset.pk, 1]))
        self.company.refresh_from_db()
        self.assertTrue(self.company.logo)                      # the horizontal logo of the chosen concept
        self.client.post(reverse('brand:choose', args=[asset.pk, 9]))                       # not a concept: nothing changes
        self.assertEqual(BrandKit.all_companies.get().chosen_name, 'Orbit')


class KitTests(Base):
    def kit_with_logo(self):
        BrandKit.all_companies.create(company=self.company, symbol='<svg viewBox="0 0 1 1"/>')

    def test_the_kit_starts_with_the_logo_at_the_discount(self):
        shown = service.quote('logo', 'standard', bundle=True).total
        before = self.balance()
        self.client.post(reverse('brand:kit_start'), {'tier': 'standard', 'expected_points': shown})
        self.assertEqual(before - self.balance(), shown)
        self.assertTrue(BrandAsset.all_companies.get().bundled)

    def test_the_rest_of_the_kit_is_one_payment_all_or_nothing(self):
        self.kit_with_logo()
        todo = [e for e in service.ELEMENTS if e != 'logo']
        total = sum(service.quote(e, 'standard', True).total for e in todo)
        page = self.client.get(reverse('brand:studio'))
        self.assertContains(page, f'data-points="{total}"')
        before = self.balance()
        self.client.post(reverse('brand:kit_rest'), {'tier': 'standard', 'expected_points': total})
        self.assertEqual((before - self.balance(), BrandAsset.all_companies.count()), (total, len(todo)))
        self.assertEqual(Job.objects.count(), len(todo))

    def test_a_kit_is_never_half_bought(self):
        self.kit_with_logo()
        todo = [e for e in service.ELEMENTS if e != 'logo']
        total = sum(service.quote(e, 'standard', True).total for e in todo)
        Wallet.objects.filter(company=self.company).update(balance=total - 1)
        self.client.post(reverse('brand:kit_rest'), {'tier': 'standard', 'expected_points': total})
        self.assertEqual((self.balance(), BrandAsset.all_companies.count(), Job.objects.count()), (total - 1, 0, 0))

    def test_a_wrong_total_buys_nothing(self):
        self.kit_with_logo()
        before = self.balance()
        self.client.post(reverse('brand:kit_rest'), {'tier': 'standard', 'expected_points': 5})
        self.assertEqual((self.balance(), BrandAsset.all_companies.count()), (before, 0))


class AccessTests(Base):
    def test_another_company_sees_no_design_and_no_file(self):
        self.create('colors')
        self.work({'ok': True, 'files': {'colors.png': png()}})
        asset = BrandAsset.all_companies.get()
        self.client.force_login(self.stranger)
        self.assertEqual(self.client.get(reverse('brand:detail', args=[asset.pk])).status_code, 404)
        self.assertEqual(self.client.get(reverse('brand:file', args=[asset.pk, 'colors.png'])).status_code, 404)
        self.assertEqual(self.client.get(reverse('brand:zip', args=[asset.pk])).status_code, 404)

    def test_files_are_served_resized_and_zipped_and_encrypted_on_disk(self):
        self.create('colors')
        self.work({'ok': True, 'files': {'colors.png': png()}})
        asset = BrandAsset.all_companies.get()
        small = self.client.get(reverse('brand:file', args=[asset.pk, 'colors.png']) + '?w=64')
        self.assertEqual(small['Content-Type'], 'image/png')
        self.assertEqual(self.client.get(reverse('brand:zip', args=[asset.pk]))['Content-Type'], 'application/zip')
        with open(BrandFile.all_companies.get().file.path, 'rb') as raw:
            self.assertNotIn(b'PNG', raw.read(16))
        self.client.post(reverse('brand:delete', args=[asset.pk]))
        self.assertEqual((BrandAsset.all_companies.count(), BrandFile.all_companies.count()), (0, 0))
