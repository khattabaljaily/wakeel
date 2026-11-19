"""Presentations: price shown = price charged (every option, with and without a source document), refunds, files, isolation."""
import io
from unittest import mock

from django.core.files.base import ContentFile
from django.test import TestCase
from django.urls import reverse
from pypdf import PdfWriter

from apps.companies.models import Membership
from apps.content.tests import make_company, make_user
from apps.credits.models import Wallet
from apps.jobs.models import Job
from apps.jobs.runner import run_job
from apps.library.models import Record

from . import service
from .models import Presentation

BUILT = {'ok': True, 'pptx': b'PK-deck', 'pdf': b'%PDF-deck', 'deck': {'slides': [{'title': 'Intro'}, {'title': 'Plan'}, {'quote': 'Q'}]}}


def pdf_bytes(pages=3):
    writer = PdfWriter()
    for _n in range(pages):
        writer.add_blank_page(200, 200)
    out = io.BytesIO()
    writer.write(out)
    return out.getvalue()


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

    def record(self, pages=3, company=None):
        record = Record(company=company or self.company, title='Plan', category='other', content_type='application/pdf')
        record.file.save('plan.pdf', ContentFile(pdf_bytes(pages)), save=False)
        record.save()
        return record

    def data(self, **extra):
        data = {'title': 'Q3 plan', 'brief': 'Our growth plan', 'language': 'en', 'slides': 10, 'tier': 'premium'}
        data.update(extra)
        return data

    def order(self, shown=None, **extra):
        data = self.data(**extra)
        pages = service.source_pages_of(Record.all_companies.filter(pk=data['source_record']).first()) if data.get('source_record') else 0
        data['confirm'] = '1'
        data['expected_points'] = service.quote(data['tier'], data['slides'], pages).total if shown is None else shown
        return self.client.post(reverse('presentations:new'), data)

    def work(self, build=BUILT):
        job = Job.objects.order_by('-pk').first()
        with mock.patch('apps.presentations.service.docai_presentation.build', return_value=build):
            run_job(job)
        job.refresh_from_db()
        return job


class PriceTests(Base):
    def test_the_confirm_page_shows_the_exact_price_and_charges_nothing(self):
        before = self.balance()
        page = self.client.post(reverse('presentations:new'), self.data())
        quote = service.quote('premium', 10)
        self.assertContains(page, f'name="expected_points" value="{quote.total}"')
        self.assertContains(page, f'${quote.usd}')
        self.assertEqual((self.balance(), Job.objects.count(), Presentation.all_companies.count()), (before, 0, 0))

    def test_every_option_and_size_is_charged_exactly_what_is_shown(self):
        for tier in ('standard', 'premium', 'ultra'):
            for slides in (5, 10, 20):
                with self.subTest(tier=tier, slides=slides):
                    Job.objects.all().delete()
                    Presentation.all_companies.all().delete()
                    before = self.balance()
                    shown = service.quote(tier, slides)
                    self.order(tier=tier, slides=slides)
                    self.assertEqual(before - self.balance(), shown.total)
                    self.assertEqual(Job.objects.get().charge_txn.delta, -shown.total)
                    Wallet.objects.filter(company=self.company).update(balance=before)

    def test_a_source_document_is_priced_and_charged_as_shown(self):
        record = self.record(pages=4)
        plain, with_doc = service.quote('premium', 10).total, service.quote('premium', 10, 4).total
        self.assertGreater(with_doc, plain)
        page = self.client.post(reverse('presentations:new'), self.data(source_record=record.pk))
        self.assertContains(page, f'name="expected_points" value="{with_doc}"')
        before = self.balance()
        self.order(source_record=record.pk)
        self.assertEqual(before - self.balance(), with_doc)
        self.assertEqual(Presentation.all_companies.get().source_pages, 4)

    def test_a_wrong_price_is_refused_without_charging_or_keeping_a_presentation(self):
        before = self.balance()
        self.order(shown=1)
        self.assertEqual((self.balance(), Job.objects.count(), Presentation.all_companies.count()), (before, 0, 0))

    def test_not_enough_balance_keeps_nothing(self):
        Wallet.objects.filter(company=self.company).update(balance=0)
        page = self.client.post(reverse('presentations:new'), {**self.data(), 'confirm': '1', 'expected_points': 1})
        self.assertContains(page, 'disabled')
        self.assertEqual((Job.objects.count(), Presentation.all_companies.count()), (0, 0))

    def test_a_request_with_neither_text_nor_document_is_not_accepted(self):
        page = self.client.post(reverse('presentations:new'), self.data(brief='', title=''))
        self.assertEqual(page.status_code, 200)
        self.assertEqual(Presentation.all_companies.count(), 0)

    def test_viewers_cannot_order(self):
        self.client.force_login(self.viewer)
        before = self.balance()
        self.order()
        self.assertEqual((Job.objects.count(), self.balance()), (0, before))


class RunTests(Base):
    def test_a_finished_deck_keeps_its_files_and_plan(self):
        self.order()
        job = self.work()
        p = Presentation.all_companies.get()
        self.assertEqual((job.status, p.status, p.outline), (Job.Status.DONE, Presentation.DONE, ['Intro', 'Plan', 'Q']))
        self.assertEqual(job.params['result_url'], reverse('presentations:detail', args=[p.pk]))
        self.assertEqual(self.client.get(reverse('presentations:file', args=[p.pk, 'pptx'])).content, b'PK-deck')
        self.assertEqual(self.client.get(reverse('presentations:file', args=[p.pk, 'preview']))['Content-Type'], 'application/pdf')

    def test_a_failed_deck_is_refunded(self):
        before = self.balance()
        self.order()
        job = self.work({'ok': False, 'code': 'x'})
        p = Presentation.all_companies.get()
        self.assertEqual((job.status, p.status, self.balance()), (Job.Status.FAILED, Presentation.FAILED, before))
        self.assertEqual(self.client.get(reverse('presentations:file', args=[p.pk, 'pptx'])).status_code, 404)

    def test_the_deck_is_built_in_the_company_identity(self):
        self.company.primary_color = '#112233'
        self.company.save()
        self.order(language='ar')
        seen = {}

        def build(chat, brief, **options):
            seen.update(options)
            return BUILT
        with mock.patch('apps.presentations.service.docai_presentation.build', side_effect=build):
            run_job(Job.objects.get())
        self.assertEqual((seen['identity']['name'], seen['identity']['primary'], seen['language'], seen['tier']), ('Alpha', '#112233', 'ar', 'premium'))

    def test_the_run_counts_the_ai_tokens(self):
        from apps.ai import client as ai
        self.order()

        def build(chat, brief, **options):
            chat('s', 'u', task='plan')
            return BUILT
        with mock.patch('apps.docops.ops.client.complete_text', return_value=ai.AIResult({'text': 'x'}, 100, 50, 0, 'claude-opus-5-5')):
            with mock.patch('apps.presentations.service.docai_presentation.build', side_effect=build):
                job = Job.objects.get()
                run_job(job)
        job.refresh_from_db()
        self.assertEqual((job.status, job.input_tokens), (Job.Status.DONE, 100))


class IsolationTests(Base):
    def test_another_company_cannot_see_open_or_delete_a_deck(self):
        self.order()
        self.work()
        p = Presentation.all_companies.get()
        self.client.force_login(self.stranger)
        for url in (reverse('presentations:detail', args=[p.pk]), reverse('presentations:file', args=[p.pk, 'pptx'])):
            self.assertEqual(self.client.get(url).status_code, 404)
        self.assertEqual(self.client.post(reverse('presentations:delete', args=[p.pk])).status_code, 404)
        self.assertEqual(Presentation.all_companies.count(), 1)
        self.assertNotContains(self.client.get(reverse('presentations:list')), 'Q3 plan')

    def test_another_companys_document_cannot_be_a_source(self):
        foreign = self.record(company=self.other)
        page = self.client.post(reverse('presentations:new'), self.data(source_record=foreign.pk))
        self.assertEqual(page.status_code, 200)
        self.assertEqual(Presentation.all_companies.count(), 0)

    def test_deleting_removes_the_files(self):
        self.order()
        self.work()
        p = Presentation.all_companies.get()
        self.client.post(reverse('presentations:delete', args=[p.pk]))
        self.assertEqual(Presentation.all_companies.count(), 0)
