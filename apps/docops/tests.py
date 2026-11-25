"""The document services: price shown = price charged (per option, per target script), refunds, isolation, downloads."""
from unittest import mock

from django.core.files.base import ContentFile
from django.test import TestCase
from django.urls import reverse

from apps.ai import client as ai
from apps.companies.models import Membership
from apps.content.tests import make_company, make_user
from apps.credits import quote as quotes
from apps.credits.models import Wallet
from apps.jobs.models import Job
from apps.jobs.runner import run_job
from apps.library.models import Record
from apps.library.tests import PDF

from . import density, ops
from .models import Operation

TEXT_SIZE = {'text_tokens': 1000, 'script': 'latin'}


class Base(TestCase):
    def setUp(self):
        self.company = make_company('A')
        self.other = make_company('B')
        self.owner = make_user('o@example.com', self.company)
        self.viewer = make_user('v@example.com', self.company, Membership.Role.VIEWER)
        self.stranger = make_user('s@example.com', self.other)
        self.client.force_login(self.owner)
        self.record = Record(company=self.company, title='Contract', category='contracts', content_type='application/pdf')
        self.record.file.save('c.pdf', ContentFile(PDF), save=False)
        self.record.save()

    def balance(self):
        return Wallet.objects.get(company=self.company).balance

    def quote(self, kind, tier='standard', language=''):
        pages = ops.page_count(self.record)
        return ops.run_quote(self.record, kind, tier, pages, language)[0]

    def start(self, kind, tier='standard', language='en', shown=None, **extra):
        data = {'tier': tier, 'language': language, 'expected_points': self.quote(kind, tier, language).total if shown is None else shown}
        data.update(extra)
        return self.client.post(reverse('docops:run', args=[self.record.pk, kind]), data)

    def work(self, handler_patch):
        job = Job.objects.order_by('-pk').first()
        with handler_patch:
            run_job(job)
        job.refresh_from_db()
        return job


class PriceTests(Base):
    def test_the_confirm_page_shows_the_points_the_job_will_charge(self):
        page = self.client.get(reverse('services:confirm', args=['summarize', self.record.pk]))
        for tier in ('standard', 'formatted', 'premium'):
            self.assertContains(page, f'data-points="{self.quote("summarize", tier, "en").total}"')
        self.assertContains(page, 'id="expectedPoints"')

    def test_every_option_is_charged_exactly_what_is_shown(self):
        for kind, tier in [(k, t) for k, tiers in ops.OPTIONS.items() for t in tiers]:
            with self.subTest(kind=kind, tier=tier):
                Job.objects.all().delete()
                Operation.all_companies.all().delete()
                shown = self.quote(kind, tier, 'en')
                before = self.balance()
                self.start(kind, tier, 'en')
                self.assertEqual(before - self.balance(), shown.total)
                job = Job.objects.get()
                self.assertEqual(job.charge_txn.delta, -shown.total)
                self.assertEqual(job.params['service'], ops.option_key(kind, tier))
                self.assertEqual(Operation.all_companies.get().job_id, job.pk)
                Wallet.objects.filter(company=self.company).update(balance=before)

    def test_a_translation_price_follows_the_script_of_the_target_language(self):
        # Prices are whole riyals now, so the difference only shows on a document big enough to cost several of them.
        with mock.patch('apps.docops.density.document_size', return_value={**TEXT_SIZE, 'text_tokens': 12000}), \
                mock.patch('apps.docops.ops.page_count', return_value=10):
            arabic, latin = self.quote('translate', 'standard', 'ar'), self.quote('translate', 'standard', 'en')
            self.assertGreater(arabic.total, latin.total)                   # writing Arabic takes more tokens
            page = self.client.get(reverse('services:confirm', args=['translate', self.record.pk]))
            self.assertContains(page, f'data-arabic="{arabic.total}"')
            self.assertContains(page, f'data-latin="{latin.total}"')
            before = self.balance()
            self.start('translate', 'standard', 'ar')
            self.assertEqual(before - self.balance(), arabic.total)

    def test_a_wrong_price_is_refused_without_charging_and_keeps_no_operation(self):
        before = self.balance()
        self.start('summarize', 'standard', 'en', shown=1)
        self.assertEqual((self.balance(), Job.objects.count(), Operation.all_companies.count()), (before, 0, 0))

    def test_not_enough_balance_keeps_no_operation_and_runs_nothing(self):
        Wallet.objects.filter(company=self.company).update(balance=0)
        self.start('summarize')
        self.assertEqual((Job.objects.count(), Operation.all_companies.count()), (0, 0))

    def test_the_price_lines_are_the_fixed_price_and_the_pages(self):
        quote = self.quote('summarize')
        self.assertEqual(sum(points for line in quote.lines for points in [line.points]), quote.total)
        self.assertEqual(len(quote.described()), len(quote.lines))


class RunTests(Base):
    def test_a_summary_job_saves_the_text_and_charges_once(self):
        self.start('summarize', 'standard', 'en', length='short')
        patch = mock.patch('apps.docops.ops.docai_summarize.summarize_document', return_value={'ok': True, 'content': 'A short summary.'})
        job = self.work(patch)
        operation = Operation.all_companies.get()
        self.assertEqual((job.status, operation.status, operation.text), (Job.Status.DONE, Operation.DONE, 'A short summary.'))
        self.assertEqual(job.params['result_url'], reverse('docops:result', args=[operation.pk]))

    def test_a_failed_run_is_refunded_and_the_operation_says_so(self):
        before = self.balance()
        self.start('translate', 'standard', 'en')
        job = self.work(mock.patch('apps.docops.ops.docai_translate.translate_document',
                                   return_value={'ok': False, 'error': 'The service had a problem.'}))
        operation = Operation.all_companies.get()
        self.assertEqual((job.status, operation.status, self.balance()), (Job.Status.FAILED, Operation.FAILED, before))
        self.assertIn('problem', operation.error)

    def test_an_exception_in_the_work_is_refunded_too(self):
        before = self.balance()
        self.start('summarize')
        job = self.work(mock.patch('apps.docops.ops.docai_summarize.summarize_document', side_effect=RuntimeError('boom')))
        self.assertEqual((job.status, Operation.all_companies.get().status, self.balance()), (Job.Status.FAILED, Operation.FAILED, before))

    def test_extract_runs_on_a_document_block_on_the_premium_tier(self):
        self.start('extract', 'standard', 'en')
        data = {k: ['x'] for k in ops.EXTRACT_KEYS}
        patch = mock.patch('apps.docops.ops.client.call_json', return_value=ai.AIResult(data, 100, 50, 0, 'claude-opus-5-5'))
        with patch as call:
            job = self.work(mock.patch('apps.docops.ops.HANDLERS', ops.HANDLERS))
        self.assertEqual(job.status, Job.Status.DONE)
        self.assertEqual(call.call_args.args[1][0]['type'], 'document')
        self.assertEqual(call.call_args.kwargs['tier'], 'premium')
        self.assertEqual(Operation.all_companies.get().data['parties'], ['x'])
        self.assertEqual(job.input_tokens, 100)                              # its tokens count in the job's cost

    def test_the_chat_given_to_enjaz_docai_runs_on_claude_and_collects_the_tokens(self):
        usage = ops._usage_collector()
        chat = ops._make_chat(usage)
        with mock.patch('apps.docops.ops.client.complete_text', return_value=ai.AIResult({'text': 'hi'}, 10, 5, 0, 'claude-opus-5-5')) as call:
            answer = chat('sys', 'user', task='translate.page', images=[b'\xff\xd8\xff'], effort='low', timeout=60)
        self.assertEqual((answer['ok'], answer['content']), (True, 'hi'))
        self.assertEqual(call.call_args.kwargs['tier'], 'premium')
        self.assertEqual(call.call_args.args[1][0]['type'], 'image')
        with mock.patch('apps.docops.ops.client.complete_text', side_effect=ai.AIError('no')):
            self.assertFalse(chat('s', 'u', task='x')['ok'])                 # never raises
        self.assertEqual(len(usage['results']), 1)

    def test_an_image_cannot_use_the_original_design_option(self):
        image = Record(company=self.company, title='Photo', content_type='image/jpeg')
        from PIL import Image
        import io
        buffer = io.BytesIO()
        Image.new('RGB', (20, 20), 'white').save(buffer, 'JPEG')
        image.file.save('p.jpg', ContentFile(buffer.getvalue()), save=False)
        image.save()
        before = self.balance()
        self.client.post(reverse('docops:run', args=[image.pk, 'translate']), {
            'tier': 'premium', 'language': 'en', 'expected_points': 100})
        self.assertEqual((self.balance(), Job.objects.count()), (before, 0))

    def test_a_pdf_longer_than_the_limit_is_cut_and_the_operation_remembers_it(self):
        import io

        from pypdf import PdfWriter
        writer, out = PdfWriter(), io.BytesIO()
        for _i in range(ops.MAX_PAGES + 3):
            writer.add_blank_page(width=100, height=100)
        writer.write(out)
        record = Record(company=self.company, title='Long', content_type='application/pdf')
        record.file.save('l.pdf', ContentFile(out.getvalue()), save=False)
        record.save()
        pages = ops.page_count(record)
        shown = ops.run_quote(record, 'summarize', 'standard', pages, 'en')[0]
        self.client.post(reverse('docops:run', args=[record.pk, 'summarize']), {
            'tier': 'standard', 'language': 'en', 'expected_points': shown.total})
        operation = Operation.all_companies.get()
        self.assertEqual((operation.pages, operation.pages_total, operation.was_cut), (ops.MAX_PAGES, ops.MAX_PAGES + 3, True))


class AccessTests(Base):
    def make_done(self, **kwargs):
        defaults = dict(company=self.company, record=self.record, kind='summarize', language='en', text='The summary',
                        status=Operation.DONE, created_by=self.owner)
        defaults.update(kwargs)
        return Operation.all_companies.create(**defaults)

    def test_viewers_read_results_but_cannot_run(self):
        operation = self.make_done()
        self.client.force_login(self.viewer)
        self.assertContains(self.client.get(reverse('docops:result', args=[operation.pk])), 'The summary')
        before = self.balance()
        self.start('summarize')
        self.assertEqual((Job.objects.count(), self.balance()), (0, before))
        self.client.post(reverse('docops:delete', args=[operation.pk]))
        self.assertTrue(Operation.all_companies.filter(pk=operation.pk).exists())

    def test_another_company_sees_nothing(self):
        operation = self.make_done()
        self.client.force_login(self.stranger)
        self.assertEqual(self.client.get(reverse('docops:result', args=[operation.pk])).status_code, 404)
        self.assertEqual(self.client.get(reverse('docops:download', args=[operation.pk, 'txt'])).status_code, 404)
        self.assertEqual(self.client.get(reverse('services:confirm', args=['summarize', self.record.pk])).status_code, 404)

    def test_downloads_are_the_formats_of_the_option_paid_for(self):
        operation = self.make_done()
        response = self.client.get(reverse('docops:download', args=[operation.pk, 'txt']))
        self.assertEqual(response.content, b'The summary')
        self.assertEqual(self.client.get(reverse('docops:download', args=[operation.pk, 'pdf'])).status_code, 404)   # not in "standard"
        self.assertEqual(self.client.get(reverse('docops:download', args=[operation.pk, 'designed-pdf'])).status_code, 404)

    def test_a_working_result_polls_its_job_and_the_panel_lists_results(self):
        operation = self.make_done(status=Operation.RUNNING, text='', job_id=77)
        self.assertContains(self.client.get(reverse('docops:result', args=[operation.pk])), 'data-job="77"')
        page = self.client.get(reverse('library:list') + f'?rec={self.record.pk}')
        self.assertContains(page, 'id="docops"')
        self.assertContains(page, reverse('docops:result', args=[operation.pk]))

    def test_the_hub_and_the_upload_path_keep_the_file_in_the_library(self):
        hub = self.client.get(reverse('services:hub'))
        self.assertContains(hub, quotes.make(ops.SERVICES['summarize'], pages=1).amount)      # the page price the card shows
        from django.core.files.uploadedfile import SimpleUploadedFile
        response = self.client.post(reverse('services:start', args=['ocr']), {'file': SimpleUploadedFile('s.pdf', PDF)})
        record = Record.all_companies.get(title='s')
        self.assertEqual((record.category, record.content_type), (Record.OTHER, 'application/pdf'))
        self.assertRedirects(response, reverse('services:confirm', args=['ocr', record.pk]))

    def test_the_file_of_a_result_leaves_with_it(self):
        import os
        operation = self.make_done(kind='word')
        operation.file.save('w.docx', ContentFile(b'PK fake'), save=True)
        path = operation.file.path
        operation.delete()
        self.assertFalse(os.path.exists(path))


class DensityTests(TestCase):
    def test_a_text_document_is_worth_less_than_a_dense_page_and_a_scan_counts_as_dense(self):
        from apps.credits import catalog
        light = density.units('summarize_document', 2, {'text_tokens': 300, 'script': 'latin'})
        scan = density.units('summarize_document', 2, {'text_tokens': None, 'script': ''})
        self.assertLess(light, scan)
        self.assertEqual(scan, 2)
        self.assertIsNone(density.units('generate_document', 2, {}))
        self.assertTrue(catalog.page_pricing('summarize_document'))
