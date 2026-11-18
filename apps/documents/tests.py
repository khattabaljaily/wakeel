"""The documents section: writing (paid jobs, priced as shown), templates, approval, the public verification page,
isolation between companies, encryption of the text."""
from unittest import mock

from django.core import mail
from django.test import TestCase, override_settings
from django.urls import reverse

from apps.ai import client as ai
from apps.audit.models import AuditEvent
from apps.companies.models import Membership
from apps.content.tests import make_company, make_user
from apps.credits import quote as quotes
from apps.credits.models import Wallet
from apps.jobs.models import Job
from apps.jobs.runner import run_job
from apps.notifications.models import Notification

from . import generate, jobs
from .models import Document, DocumentContent, DocumentTemplate

DESIGN = '<style>h1{color:#7c3aed}</style><h1>Salary letter</h1><p>Dear {{name}}, your salary is {{salary}}.</p>'
FILL = {'values': [{'name': 'name', 'value': 'Sara'}, {'name': 'salary', 'value': '1200 USD'}]}
AI_FORM = {'doc_type': 'Salary letter', 'language': 'en', 'category': 'letters', 'recipient': 'The Bank',
           'instructions': 'For Sara, a bank letter'}


def result(data):
    return ai.AIResult(data, 100, 50, 0, 'claude-opus-5-5')


class Base(TestCase):
    def setUp(self):
        self.company = make_company('A')
        self.other = make_company('B')
        self.owner = make_user('o@example.com', self.company)
        self.member = make_user('m@example.com', self.company, Membership.Role.EDITOR)
        self.viewer = make_user('v@example.com', self.company, Membership.Role.VIEWER)
        self.stranger = make_user('s@example.com', self.other)
        self.client.force_login(self.owner)

    def balance(self):
        return Wallet.objects.get(company=self.company).balance

    def template(self, html=DESIGN, name='Salary letter', company=None):
        return DocumentTemplate.all_companies.create(company=company or self.company, name=name, subject=name, html=html,
                                                     category='letters', language='en', created_by=self.owner)

    def document(self, **kwargs):
        defaults = dict(company=self.company, title='Letter', kind='letter', language='en', created_by=self.owner)
        defaults.update(kwargs)
        doc = Document(**defaults)
        doc.subject, doc.body = 'Salary', 'He works here.'
        doc.save()
        return doc

    def run_next(self, **calls):
        """Run the queued job with the AI mocked (a list of results, or an exception for the call)."""
        job = Job.objects.order_by('-pk').first()
        side = calls.get('error') or [result(d) for d in calls['data']]
        with mock.patch('apps.documents.generate.client.call_json', side_effect=side) as call:
            run_job(job)
        job.refresh_from_db()
        return job, call


class WritingTests(Base):
    def test_the_page_shows_the_price_of_each_action_and_the_charge_equals_it(self):
        write, first = quotes.make('fill_document').total, quotes.bundle(quotes.make('generate_template'), quotes.make('fill_document')).total
        page = self.client.get(reverse('documents:new', args=['document']))
        self.assertContains(page, f'name="expected_points_write" value="{write}"')
        self.assertContains(page, f'name="expected_points_template" value="{first}"')
        self.assertContains(page, f'${write / 1000:,.2f}')
        self.template()
        before = self.balance()
        self.client.post(reverse('documents:new', args=['document']),
                         {**AI_FORM, 'action': 'write', 'expected_points_write': write})
        self.assertEqual(before - self.balance(), write)                                  # exactly the shown price
        self.assertEqual(Job.objects.get().charge_txn.delta, -write)

    def test_a_template_less_type_asks_first_with_the_whole_price_and_charges_nothing(self):
        before = self.balance()
        page = self.client.post(reverse('documents:new', args=['document']), {**AI_FORM, 'action': 'write'})
        self.assertContains(page, 'name="action" value="write_new_template"')
        first = quotes.bundle(quotes.make('generate_template'), quotes.make('fill_document'))
        self.assertContains(page, f'${first.usd}')
        for text, usd in first.described():                                              # the lines of the price are listed
            self.assertContains(page, usd)
        self.assertEqual((self.balance(), Job.objects.count()), (before, 0))

    def test_agreeing_designs_the_template_and_writes_the_document_for_the_shown_total(self):
        first = quotes.bundle(quotes.make('generate_template'), quotes.make('fill_document')).total
        before = self.balance()
        self.client.post(reverse('documents:new', args=['document']),
                         {**AI_FORM, 'action': 'write_new_template', 'expected_points_template': first})
        self.assertEqual(before - self.balance(), first)
        job, call = self.run_next(data=[{'subject': 'Salary letter', 'html': DESIGN}, FILL])
        self.assertEqual(job.status, Job.Status.DONE)
        doc = Document.all_companies.get()
        self.assertEqual((doc.values, doc.recipient, doc.status, doc.written_by_ai),
                         ({'name': 'Sara', 'salary': '1,200.00 USD'}, 'The Bank', Document.APPROVED, True))
        self.assertTrue(DocumentTemplate.all_companies.filter(company=self.company, key='salary letter').exists())
        self.assertEqual(job.params['result_url'], reverse('documents:edit', args=[doc.pk]))
        self.assertEqual([c.kwargs['tier'] for c in call.call_args_list], ['premium', 'premium'])

    def test_the_next_document_of_the_type_pays_only_the_fill(self):
        self.template()
        self.client.post(reverse('documents:new', args=['document']),
                         {**AI_FORM, 'action': 'write', 'expected_points_write': quotes.make('fill_document').total})
        self.run_next(data=[FILL])
        self.assertEqual(Job.objects.get().charge_txn.delta, -quotes.make('fill_document').total)
        self.assertEqual(DocumentTemplate.all_companies.filter(company=self.company).count(), 1)

    def test_a_wrong_price_is_refused_without_charging(self):
        self.template()
        before = self.balance()
        self.client.post(reverse('documents:new', args=['document']), {**AI_FORM, 'action': 'write', 'expected_points_write': 1})
        self.assertEqual((self.balance(), Job.objects.count(), Document.all_companies.count()), (before, 0, 0))

    def test_a_failed_run_gives_the_charge_back_and_makes_no_document(self):
        self.template()
        before = self.balance()
        self.client.post(reverse('documents:new', args=['document']),
                         {**AI_FORM, 'action': 'write', 'expected_points_write': quotes.make('fill_document').total})
        job, _call = self.run_next(error=ai.AIError('failed'))
        self.assertEqual(job.status, Job.Status.FAILED)
        self.assertEqual((self.balance(), Document.all_companies.count()), (before, 0))

    def test_a_design_with_no_blanks_is_refused_and_given_back(self):
        before = self.balance()
        first = quotes.bundle(quotes.make('generate_template'), quotes.make('fill_document')).total
        self.client.post(reverse('documents:new', args=['document']),
                         {**AI_FORM, 'action': 'write_new_template', 'expected_points_template': first})
        job, _call = self.run_next(data=[{'subject': 'x', 'html': '<p>No blanks here</p>'}])
        self.assertEqual(job.status, Job.Status.FAILED)
        self.assertEqual((self.balance(), DocumentTemplate.all_companies.count()), (before, 0))

    def test_not_enough_balance_never_calls_the_ai(self):
        self.template()
        Wallet.objects.filter(company=self.company).update(balance=0)
        self.client.post(reverse('documents:new', args=['document']),
                         {**AI_FORM, 'action': 'write', 'expected_points_write': quotes.make('fill_document').total})
        self.assertEqual(Job.objects.count(), 0)

    def test_a_member_types_a_letter_for_free(self):
        before = self.balance()
        self.client.post(reverse('documents:new', args=['letter']), {
            'manual': '1', 'title': 'Salary letter', 'recipient': 'The Bank', 'language': 'en', 'doc_date': '2026-11-01',
            'subject': 'Salary', 'body': 'He works here.', 'category': 'letters', 'action': 'save'})
        doc = Document.all_companies.get()
        self.assertEqual((doc.subject, doc.body, self.balance()), ('Salary', 'He works here.', before))

    def test_the_working_page_polls_the_job(self):
        self.template()
        self.client.post(reverse('documents:new', args=['document']),
                         {**AI_FORM, 'action': 'write', 'expected_points_write': quotes.make('fill_document').total})
        job = Job.objects.get()
        page = self.client.get(reverse('documents:working', args=[job.pk]))
        self.assertContains(page, f'data-job="{job.pk}"')
        self.client.force_login(self.stranger)
        self.assertEqual(self.client.get(reverse('documents:working', args=[job.pk])).status_code, 404)


class RewriteTests(Base):
    def test_the_rewrite_price_is_shown_charged_and_changes_a_text_document(self):
        doc = self.document()
        page = self.client.get(reverse('documents:edit', args=[doc.pk]))
        price = quotes.make('generate_document').total
        self.assertContains(page, f'name="expected_points" value="{price}"')
        before = self.balance()
        self.client.post(reverse('documents:rewrite', args=[doc.pk]), {'notes': 'shorter', 'expected_points': price})
        self.assertEqual(before - self.balance(), price)
        job, _call = self.run_next(data=[{'subject': 'Short', 'body': 'Short text.'}])
        doc.refresh_from_db()
        self.assertEqual((job.status, doc.subject, doc.body), (Job.Status.DONE, 'Short', 'Short text.'))

    def test_a_designed_document_is_rewritten_at_the_fill_price(self):
        doc = self.document()
        doc.design, doc.values = DESIGN, {'name': 'Sara', 'salary': '1000'}
        doc.save()
        price = quotes.make('fill_document').total
        self.client.post(reverse('documents:rewrite', args=[doc.pk]), {'notes': 'raise it', 'expected_points': price})
        self.run_next(data=[{'values': [{'name': 'name', 'value': 'Sara'}, {'name': 'salary', 'value': '1500'}]}])
        doc.refresh_from_db()
        self.assertEqual(doc.values['salary'], '1,500.00')                  # money is written 1,500.00

    def test_a_failed_rewrite_changes_nothing_and_costs_nothing(self):
        doc = self.document()
        before = self.balance()
        price = quotes.make('generate_document').total
        self.client.post(reverse('documents:rewrite', args=[doc.pk]), {'notes': 'x', 'expected_points': price})
        self.run_next(error=ai.AIError('failed'))
        doc.refresh_from_db()
        self.assertEqual((doc.body, self.balance()), ('He works here.', before))

    def test_an_empty_request_and_viewers_are_refused(self):
        doc = self.document()
        self.client.post(reverse('documents:rewrite', args=[doc.pk]), {'notes': ' '})
        self.assertEqual(Job.objects.count(), 0)
        self.client.force_login(self.viewer)
        self.client.post(reverse('documents:rewrite', args=[doc.pk]), {'notes': 'x', 'expected_points': 100})
        self.assertEqual(Job.objects.count(), 0)


class TemplateTests(Base):
    def test_redesign_shows_the_design_price_and_charges_it(self):
        template = self.template()
        page = self.client.get(reverse('documents:templates'))
        price = quotes.make('generate_template').total
        self.assertContains(page, f'name="expected_points" value="{price}"')
        before = self.balance()
        self.client.post(reverse('documents:template_redesign', args=[template.pk]), {'notes': 'blue', 'expected_points': price})
        self.assertEqual(before - self.balance(), price)
        self.run_next(data=[{'subject': 'Salary letter', 'html': '<h1>New {{x}}</h1>'}])
        template.refresh_from_db()
        self.assertEqual(template.html, '<h1>New {{x}}</h1>')

    def test_a_designed_template_is_filled_by_hand_for_free(self):
        template = self.template()
        before = self.balance()
        self.client.post(reverse('documents:template_use', args=[template.pk]), {'blank-0': 'Omar', 'blank-1': '900'})
        doc = Document.all_companies.get()
        self.assertEqual((doc.values, self.balance(), doc.include_qr), ({'name': 'Omar', 'salary': '900'}, before, False))

    def test_a_text_document_is_kept_as_a_template_and_used_again(self):
        doc = self.document()
        doc.body = 'Dear {{name}}'
        doc.save()
        self.client.post(reverse('documents:template_save', args=[doc.pk]), {'name': 'Greeting'})
        template = DocumentTemplate.all_companies.get()
        self.client.post(reverse('documents:template_use', args=[template.pk]), {'blank-0': 'Omar'})
        self.assertEqual(Document.all_companies.order_by('-pk').first().body, 'Dear Omar')
        self.client.post(reverse('documents:template_save', args=[doc.pk]), {'name': 'greeting'})     # same type again
        self.assertEqual(DocumentTemplate.all_companies.count(), 1)

    def test_another_company_never_sees_or_uses_a_template(self):
        template = self.template()
        self.client.force_login(self.stranger)
        self.assertEqual(self.client.get(reverse('documents:template_use', args=[template.pk])).status_code, 404)
        self.assertNotContains(self.client.get(reverse('documents:templates')), 'Salary letter')
        self.assertNotContains(self.client.get(reverse('library:list')), 'Salary letter')

    def test_the_library_lists_templates_and_never_the_text_of_documents(self):
        self.template()
        self.document(title='Secret letter')
        page = self.client.get(reverse('library:list'))
        self.assertContains(page, 'Salary letter')
        self.assertNotContains(page, 'He works here')
        self.assertContains(self.client.get(reverse('library:list') + '?tpl=%d' % DocumentTemplate.all_companies.get().pk), 'documents/d/templates')


class ImportTests(Base):
    def make_record(self):
        from django.core.files.base import ContentFile

        from apps.library.models import Record
        from apps.library.tests import PDF
        record = Record(company=self.company, title='Offer', doc_type='Offer letter', category='contracts', content_type='application/pdf')
        record.file.save('x.pdf', ContentFile(PDF), save=False)
        record.save()
        return record

    def test_importing_is_free_makes_the_template_and_is_limited_per_day(self):
        record = self.make_record()
        Wallet.objects.filter(company=self.company).update(balance=0)       # a company with no balance can still import
        for _i in range(jobs.FREE_IMPORTS_PER_DAY):
            self.client.post(reverse('documents:template_import', args=[record.pk]))
        self.assertEqual(Job.objects.count(), jobs.FREE_IMPORTS_PER_DAY)
        self.client.post(reverse('documents:template_import', args=[record.pk]))                # the sixth is refused
        self.assertEqual(Job.objects.count(), jobs.FREE_IMPORTS_PER_DAY)
        job = Job.objects.first()
        with mock.patch('apps.documents.generate.client.call_json',
                        return_value=result({'subject': 'Offer', 'html': '<p>Hi {{name}}</p>', 'language': 'en'})) as call:
            run_job(job)
        template = DocumentTemplate.all_companies.get()
        self.assertEqual((template.name, template.category, template.language), ('Offer letter', 'contracts', 'en'))
        self.assertEqual(call.call_args.args[1][0]['type'], 'document')                          # the paper itself is sent
        self.assertIsNone(job.charge_txn)

    def test_viewers_cannot_import(self):
        record = self.make_record()
        self.client.force_login(self.viewer)
        self.client.post(reverse('documents:template_import', args=[record.pk]))
        self.assertEqual(Job.objects.count(), 0)


class AccessAndStorageTests(Base):
    def test_viewers_read_but_do_not_write_and_strangers_see_nothing(self):
        doc = self.document()
        self.client.force_login(self.viewer)
        self.assertEqual(self.client.get(reverse('documents:issued')).status_code, 200)
        self.assertEqual(self.client.get(reverse('documents:edit', args=[doc.pk])).status_code, 302)
        self.assertEqual(self.client.post(reverse('documents:delete', args=[doc.pk])).status_code, 302)
        self.assertTrue(Document.all_companies.filter(pk=doc.pk).exists())
        self.client.force_login(self.stranger)
        self.assertEqual(self.client.get(reverse('documents:print', args=[doc.pk])).status_code, 404)
        self.assertNotContains(self.client.get(reverse('documents:issued')), 'Letter')

    def test_the_text_is_stored_encrypted_apart_from_the_document(self):
        doc = self.document()
        row = DocumentContent.all_companies.get(document=doc)
        self.assertNotIn(b'He works here', bytes(row.payload))
        self.assertEqual(Document.all_companies.get(pk=doc.pk).body, 'He works here.')

    def test_opening_a_document_is_logged_and_the_issued_log_shows_no_text(self):
        doc = self.document()
        self.client.get(reverse('documents:edit', args=[doc.pk]))
        self.assertTrue(AuditEvent.all_companies.filter(company=self.company, action=AuditEvent.DOC_OPENED).exists())
        self.assertNotContains(self.client.get(reverse('documents:issued')), 'He works here')

    def test_text_is_escaped_in_print_and_the_qr_only_when_asked(self):
        doc = self.document()
        doc.body = '<script>alert(1)</script>'
        doc.save()
        page = self.client.get(reverse('documents:print', args=[doc.pk]) + '?html=1')
        self.assertNotContains(page, '<script>alert(1)</script>')
        self.assertNotContains(page, 'class="verify"')
        doc.include_qr = True
        doc.save()
        self.assertContains(self.client.get(reverse('documents:print', args=[doc.pk]) + '?html=1'), 'class="verify"')


class ApprovalTests(Base):
    def setUp(self):
        super().setUp()
        self.company.documents_need_approval = True
        self.company.save()

    def test_a_members_document_starts_as_a_draft_and_a_managers_is_approved(self):
        self.client.force_login(self.member)
        self.client.post(reverse('documents:new', args=['letter']), {
            'manual': '1', 'title': 'L', 'language': 'en', 'doc_date': '2026-11-01', 'subject': 'S', 'body': 'B', 'category': 'letters'})
        self.assertEqual(Document.all_companies.get().status, Document.DRAFT)
        self.client.force_login(self.owner)
        self.client.post(reverse('documents:new', args=['letter']), {
            'manual': '1', 'title': 'L2', 'language': 'en', 'doc_date': '2026-11-01', 'subject': 'S', 'body': 'B', 'category': 'letters'})
        self.assertEqual(Document.all_companies.get(title='L2').status, Document.APPROVED)

    def test_the_whole_flow_and_nothing_goes_out_before_approval(self):
        doc = self.document(created_by=self.member, status=Document.DRAFT)
        self.client.force_login(self.member)
        for name in ('documents:print', 'documents:pdf', 'documents:docx'):
            self.assertEqual(self.client.get(reverse(name, args=[doc.pk])).status_code, 403, name)
        mail.outbox.clear()
        self.client.post(reverse('documents:submit', args=[doc.pk]))
        doc.refresh_from_db()
        self.assertEqual(doc.status, Document.PENDING)
        self.assertTrue(Notification.objects.filter(user=self.owner, kind='document_pending').exists())    # the bell
        self.assertEqual([m.to for m in mail.outbox], [[self.owner.email]])                              # and by e-mail
        self.assertNotIn('He works here', mail.outbox[0].body)                                         # never the text
        self.client.post(reverse('documents:review', args=[doc.pk]), {'decision': 'approve'})          # a member cannot approve
        doc.refresh_from_db()
        self.assertEqual(doc.status, Document.PENDING)
        self.client.force_login(self.owner)
        self.client.post(reverse('documents:review', args=[doc.pk]), {'decision': 'approve', 'note': 'ok'})
        doc.refresh_from_db()
        self.assertEqual((doc.status, doc.reviewed_by), (Document.APPROVED, self.owner))
        self.assertTrue(Notification.objects.filter(user=self.member, kind='document_approved').exists())
        self.client.force_login(self.member)
        self.assertEqual(self.client.get(reverse('documents:print', args=[doc.pk]) + '?html=1').status_code, 200)

    def test_a_rejection_and_editing_an_approved_text_need_approval_again(self):
        doc = self.document(created_by=self.member, status=Document.PENDING)
        self.client.force_login(self.owner)
        self.client.post(reverse('documents:review', args=[doc.pk]), {'decision': 'reject', 'note': 'no'})
        doc.refresh_from_db()
        self.assertEqual(doc.status, Document.REJECTED)
        doc.status = Document.APPROVED
        doc.save()
        self.client.force_login(self.member)
        self.client.post(reverse('documents:edit', args=[doc.pk]), {
            'title': 'Letter', 'language': 'en', 'doc_date': '2026-11-01', 'subject': 'S', 'body': 'changed', 'category': 'letters'})
        doc.refresh_from_db()
        self.assertEqual(doc.status, Document.DRAFT)


class VerifyTests(Base):
    def test_the_public_page_shows_the_document_without_signing_in_and_says_when_cancelled(self):
        doc = self.document(include_qr=True)
        code = doc.ensure_code()
        self.client.logout()
        page = self.client.get(reverse('verify', args=[code]))
        self.assertContains(page, 'A')                                                            # the company name
        self.assertContains(page, code)
        self.assertEqual(page['X-Robots-Tag'], 'noindex, nofollow')
        self.assertNotContains(page, self.owner.email)                                            # who issued it is never shown
        self.client.force_login(self.owner)
        self.client.post(reverse('documents:revoke', args=[doc.pk]))
        self.client.logout()
        self.assertContains(self.client.get(reverse('verify', args=[code])), 'cancelled')
        self.assertEqual(self.client.get(reverse('verify', args=['x' * 12])).status_code, 404)

    def test_only_managers_cancel(self):
        doc = self.document(include_qr=True)
        doc.ensure_code()
        self.client.force_login(self.member)
        self.assertEqual(self.client.post(reverse('documents:revoke', args=[doc.pk])).status_code, 403)

    @override_settings(CACHES={'default': {'BACKEND': 'django.core.cache.backends.locmem.LocMemCache', 'LOCATION': 'verify-rate'}})
    def test_the_page_is_rate_limited(self):
        self.client.logout()
        codes = [self.client.get(reverse('verify', args=['abcdefgh%02d' % i])).status_code for i in range(33)]
        self.assertEqual(codes[-1], 429)


class PdfTests(Base):
    def test_without_a_pdf_machine_the_pdf_address_is_404_and_the_buttons_hidden(self):
        doc = self.document()
        with mock.patch('apps.documents.pdf.available', return_value=False):
            self.assertEqual(self.client.get(reverse('documents:pdf', args=[doc.pk])).status_code, 404)
            self.assertNotContains(self.client.get(reverse('documents:edit', args=[doc.pk])), 'Download PDF')

    def test_the_word_file_downloads_and_is_logged(self):
        doc = self.document()
        response = self.client.get(reverse('documents:docx', args=[doc.pk]))
        self.assertEqual(response.status_code, 200)
        self.assertTrue(response.content.startswith(b'PK'))
        self.assertTrue(AuditEvent.all_companies.filter(company=self.company, action=AuditEvent.DOC_OPENED).exists())

    def test_the_e_mail_carries_the_pdf_and_bad_input_is_refused(self):
        doc = self.document()
        with mock.patch('apps.documents.pdf.available', return_value=True), \
                mock.patch('apps.documents.views.pdf_tools.html_to_pdf', return_value=b'%PDF-1.4 fake'):
            self.client.post(reverse('documents:email', args=[doc.pk]), {'to': 'bad', 'message': 'x'})
            self.assertEqual(len(mail.outbox), 0)
            self.client.post(reverse('documents:email', args=[doc.pk]), {'to': 'bank@example.com', 'message': 'Hello'})
        self.assertEqual(mail.outbox[0].to, ['bank@example.com'])
        self.assertEqual(mail.outbox[0].attachments[0][0], 'letter.pdf')
        self.assertTrue(AuditEvent.all_companies.filter(company=self.company, action=AuditEvent.DOC_EMAILED).exists())
