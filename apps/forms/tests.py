"""Forms and surveys: building, the public page (strangers' answers are not trusted), team forms, results, and the price:
shown = charged, once, when the form is made."""
import datetime
from unittest import mock

from django.conf import settings
from django.core.cache import cache
from django.test import TestCase, override_settings
from django.urls import reverse
from django.utils import timezone

from apps.companies.models import Membership
from apps.content.tests import make_company, make_user
from apps.credits.models import Wallet, WalletTransaction
from apps.notifications.models import Notification

from . import views
from .models import Answer, Form, Question, Response


class Base(TestCase):
    def setUp(self):
        cache.clear()
        self.company = make_company('Alpha')
        self.other = make_company('Beta')
        self.owner = make_user('owner@example.com', self.company)
        self.member = make_user('member@example.com', self.company, Membership.Role.EDITOR)
        self.viewer = make_user('viewer@example.com', self.company, Membership.Role.VIEWER)
        self.english()
        self.client.force_login(self.owner)

    def english(self):
        self.client.cookies[settings.LANGUAGE_COOKIE_NAME] = 'en'          # the pages in English: the texts below are their source

    def logout(self):
        self.client.logout()                                                 # (it clears the cookies too)
        self.english()

    def balance(self):
        return Wallet.objects.get(company=self.company).balance

    def fund(self, points, **extra):
        Wallet.objects.filter(company=self.company).update(balance=points, **extra)

    def make(self, shown=None, **kw):
        data = {'title': 'Lunch survey', 'audience': 'public', 'expected_points': views.price().total if shown is None else shown}
        data.update(kw)
        self.client.post(reverse('forms:new'), data)
        return Form.all_companies.filter(company=self.company).order_by('-id').first()

    def ask(self, form, text, kind='short', options='', required=False):
        self.client.post(reverse('forms:question_new', args=[form.pk]), {'kind': kind, 'text': text, 'options': options,
                                                                          'required': 'on' if required else ''})
        return Question.all_companies.filter(form=form).order_by('-id').first()


class Building(Base):
    def test_an_editor_makes_a_form_with_a_random_link_and_questions_in_order(self):
        form = self.make()
        self.assertEqual((form.author, form.audience, len(form.code)), (self.owner, 'public', 12))
        self.ask(form, 'Which day?', 'choice', 'Monday\nTuesday')
        b = self.ask(form, 'Why?', 'long')
        self.assertEqual([q.text for q in Question.all_companies.filter(form=form)], ['Which day?', 'Why?'])
        self.client.post(reverse('forms:question_move', args=[form.pk, b.pk]), {'to': 'up'})
        self.assertEqual([q.text for q in Question.all_companies.filter(form=form)], ['Why?', 'Which day?'])
        page = self.client.get(reverse('forms:detail', args=[form.pk]))
        self.assertContains(page, reverse('fill', args=[form.code]))
        self.assertContains(page, '<svg')                                      # the QR code

    def test_choice_questions_need_two_different_choices(self):
        form = self.make()
        page = self.client.post(reverse('forms:question_new', args=[form.pk]), {'kind': 'choice', 'text': 'Pick', 'options': 'Only one'})
        self.assertEqual(page.status_code, 200)
        self.assertFalse(Question.all_companies.filter(form=form).exists())
        self.client.post(reverse('forms:question_new', args=[form.pk]), {'kind': 'choice', 'text': 'Pick', 'options': 'A\nA'})
        self.assertFalse(Question.all_companies.filter(form=form).exists())

    def test_a_viewer_cannot_build_and_another_company_cannot_see_it(self):
        form = self.make()
        self.client.force_login(self.viewer)
        self.assertEqual(self.client.get(reverse('forms:list')).status_code, 302)
        before = self.balance()
        self.client.post(reverse('forms:new'), {'title': 'x', 'audience': 'public', 'expected_points': views.price().total})
        self.assertEqual((Form.all_companies.count(), self.balance()), (1, before))
        self.client.force_login(make_user('s@example.com', self.other))
        for url in (reverse('forms:detail', args=[form.pk]), reverse('forms:results', args=[form.pk]), reverse('forms:results_csv', args=[form.pk])):
            self.assertEqual(self.client.get(url).status_code, 404)
        self.assertEqual(self.client.post(reverse('forms:delete', args=[form.pk])).status_code, 404)
        self.assertNotContains(self.client.get(reverse('forms:list')), 'Lunch survey')

    def test_closing_and_reopening(self):
        form = self.make()
        self.client.post(reverse('forms:toggle', args=[form.pk]))
        form.refresh_from_db()
        self.assertFalse(form.accepting)
        self.client.post(reverse('forms:toggle', args=[form.pk]))
        form.refresh_from_db()
        self.assertTrue(form.accepting)
        form.closes_on = timezone.localdate() - datetime.timedelta(days=1)
        self.assertFalse(form.accepting)


class Answering(Base):
    def setUp(self):
        super().setUp()
        self.form = self.make()
        self.day = self.ask(self.form, 'Which day?', 'choice', 'Monday\nTuesday', required=True)
        self.likes = self.ask(self.form, 'What do you like?', 'multi', 'Pizza\nSalad\nSoup')
        self.rate = self.ask(self.form, 'How was it?', 'rating')
        self.note = self.ask(self.form, 'Anything else?', 'long')
        self.url = reverse('fill', args=[self.form.code])
        self.logout()

    def send(self, **data):
        return self.client.post(self.url, {f'q{self.day.pk}': 'Monday', **data})

    def test_a_visitor_with_no_account_answers_and_nothing_about_them_is_kept(self):
        self.assertContains(self.client.get(self.url), 'Lunch survey')
        response = self.send(**{f'q{self.likes.pk}': ['Pizza', 'Soup'], f'q{self.rate.pk}': '4', f'q{self.note.pk}': 'Thanks'})
        self.assertContains(response, 'Your answers were sent')
        reply = Response.all_companies.get(form=self.form)
        self.assertIsNone(reply.user)
        shown = {a.question.text: a.shown for a in Answer.all_companies.filter(response=reply).select_related('question')}
        self.assertEqual(shown, {'Which day?': 'Monday', 'What do you like?': 'Pizza, Soup', 'How was it?': '4', 'Anything else?': 'Thanks'})
        self.assertEqual(self.client.get(self.url)['X-Robots-Tag'], 'noindex, nofollow')

    def test_a_signed_in_person_of_another_company_answers_into_the_forms_company(self):
        self.client.force_login(make_user('s@example.com', self.other))
        self.send()
        self.assertEqual(Response.all_companies.get(form=self.form).company, self.company)

    def test_a_real_browser_can_send_the_answers(self):
        """A browser posts 'Origin: null' from a page served with 'Referrer-Policy: no-referrer', and the CSRF check then
        refuses the form (the test client sends no Origin, so only this test sees it)."""
        from django.test import Client
        browser = Client(enforce_csrf_checks=True)
        page = browser.get(self.url)
        self.assertNotEqual(page['Referrer-Policy'], 'no-referrer')
        browser.post(self.url, {f'q{self.day.pk}': 'Monday', 'csrfmiddlewaretoken': browser.cookies[settings.CSRF_COOKIE_NAME].value},
                     HTTP_ORIGIN='http://testserver')
        self.assertEqual(Response.all_companies.filter(form=self.form).count(), 1)

    def test_a_required_question_a_bad_choice_and_a_bad_rating_are_refused_and_typing_is_kept(self):
        response = self.client.post(self.url, {f'q{self.rate.pk}': '9', f'q{self.note.pk}': 'keep me'})
        self.assertContains(response, 'This question needs an answer', status_code=400)
        self.assertContains(response, 'Choose a rating from 1 to 5', status_code=400)
        self.assertContains(response, 'keep me', status_code=400)
        self.assertFalse(Response.all_companies.filter(form=self.form).exists())
        bad = self.client.post(self.url, {f'q{self.day.pk}': 'Sunday'})
        self.assertContains(bad, 'Choose one of the listed choices', status_code=400)

    def test_a_filled_hidden_field_is_a_robot_and_is_thanked_but_not_kept(self):
        self.send(website='http://spam.example')
        self.assertFalse(Response.all_companies.filter(form=self.form).exists())

    def test_a_closed_form_and_a_wrong_link(self):
        self.form.is_open = False
        self.form.save()
        self.assertContains(self.client.get(self.url), 'This form is closed')
        self.assertEqual(self.send().status_code, 200)
        self.assertFalse(Response.all_companies.filter(form=self.form).exists())
        self.assertEqual(self.client.get(reverse('fill', args=['nonexistent1'])).status_code, 404)

    def test_too_many_answers_from_one_address_are_held_back(self):
        codes = [self.send().status_code for _i in range(14)]
        self.assertEqual(codes[:12], [200] * 12)
        self.assertEqual(codes[12:], [429, 429])
        self.assertEqual(Response.all_companies.filter(form=self.form).count(), 12)

    def test_the_author_is_told_once_while_the_last_notice_is_unread(self):
        self.send()
        self.send()
        told = Notification.objects.filter(user=self.owner, kind='form_answer')
        self.assertEqual(told.count(), 1)
        self.assertEqual((told[0].url, told[0].company), (reverse('forms:results', args=[self.form.pk]), self.company))
        told.update(read_at=timezone.now())
        self.send()
        self.assertEqual(Notification.objects.filter(kind='form_answer').count(), 2)


class TeamForm(Base):
    def setUp(self):
        super().setUp()
        self.form = self.make(audience='team')
        self.q = self.ask(self.form, 'Your view?')
        self.url = reverse('fill', args=[self.form.code])
        self.logout()

    def test_it_asks_to_sign_in_and_keeps_one_answer_per_person_with_their_name(self):
        self.assertRedirects(self.client.get(self.url), f"{reverse('accounts:login')}?next={self.url.replace('/', '%2F')}", fetch_redirect_response=False)
        self.client.force_login(self.member)
        self.client.post(self.url, {f'q{self.q.pk}': 'Fine'})
        self.assertEqual(Response.all_companies.get(form=self.form).user, self.member)
        self.assertContains(self.client.get(self.url), 'You already answered')
        self.client.post(self.url, {f'q{self.q.pk}': 'Again'})
        self.assertEqual(Response.all_companies.filter(form=self.form).count(), 1)

    def test_someone_from_another_company_or_a_client_is_turned_away(self):
        self.client.force_login(make_user('s@example.com', self.other))
        self.assertEqual(self.client.get(self.url).status_code, 403)
        self.client.force_login(make_user('c@example.com', self.company, Membership.Role.CLIENT))
        self.assertEqual(self.client.get(self.url).status_code, 403)


class Reading(Base):
    def test_summary_csv_and_deleting_an_answer(self):
        form = self.make()
        day = self.ask(form, 'Which day?', 'choice', 'Monday\nTuesday')
        rate = self.ask(form, 'How was it?', 'rating')
        note = self.ask(form, 'Notes', 'short')
        for d, r, n in (('Monday', '5', '=HYPERLINK("http://x")'), ('Monday', '3', 'ok'), ('Tuesday', '4', '')):
            reply = Response.all_companies.create(company=self.company, form=form)
            for q, v in ((day, d), (rate, r), (note, n)):
                if v:
                    Answer.all_companies.create(company=self.company, response=reply, question=q, value=v)
        page = self.client.get(reverse('forms:results', args=[form.pk]))
        summary = {s['question'].text: s for s in page.context['summary']}
        self.assertEqual([(b['label'], b['n']) for b in summary['Which day?']['bars']], [('Monday', 2), ('Tuesday', 1)])
        self.assertEqual(summary['How was it?']['average'], 4.0)
        csv = self.client.get(reverse('forms:results_csv', args=[form.pk]))
        self.assertEqual(csv['Content-Type'], 'text/csv; charset=utf-8')
        text = csv.content.decode('utf-8')
        self.assertIn("'=HYPERLINK", text)                                         # a stranger's text never runs as a formula
        self.assertEqual(len(text.strip().splitlines()), 4)
        self.client.post(reverse('forms:response_delete', args=[form.pk, Response.all_companies.filter(form=form).first().pk]))
        self.assertEqual(Response.all_companies.filter(form=form).count(), 2)


class Paying(Base):
    """A form is paid once, when it is created, at the price on the button. Its answers cost nothing."""

    def test_the_price_on_the_button_is_the_price_charged_and_written_in_the_ledger(self):
        self.fund(1000)
        quote = views.price()
        page = self.client.get(reverse('forms:list'))
        self.assertContains(page, f'name="expected_points" value="{quote.total}"')
        self.assertContains(page, f'${quote.usd}')
        self.assertEqual(quote.total, 250)                                          # the owner's price: $0.25
        self.assertIsNotNone(self.make())
        self.assertEqual(self.balance(), 1000 - quote.total)
        row = WalletTransaction.objects.get(company=self.company, service_key='create_form')
        self.assertEqual((row.delta, row.breakdown[0]['points']), (-quote.total, quote.total))

    def test_a_different_price_is_refused_without_charging_or_making_a_form(self):
        self.fund(1000)
        page = self.client.post(reverse('forms:new'), {'title': 'x', 'audience': 'public', 'expected_points': 1})
        self.assertContains(page, 'The price changed')
        self.assertEqual((self.balance(), Form.all_companies.count()), (1000, 0))

    def test_without_enough_balance_no_form_is_made_and_the_page_says_why(self):
        self.fund(100)
        page = self.client.post(reverse('forms:new'), {'title': 'Too poor', 'audience': 'public', 'expected_points': views.price().total})
        self.assertContains(page, 'Your balance is not enough')
        self.assertContains(page, 'collapse show')                               # the form stays open with what was typed
        self.assertEqual((self.balance(), Form.all_companies.count()), (100, 0))

    def test_a_failed_save_gives_the_money_back(self):
        self.fund(1000)
        with mock.patch.object(Form, 'save', side_effect=RuntimeError('database')):
            with self.assertRaises(RuntimeError):
                self.client.post(reverse('forms:new'), {'title': 'x', 'audience': 'public', 'expected_points': views.price().total})
        self.assertEqual((self.balance(), WalletTransaction.objects.filter(service_key='create_form').count()), (1000, 0))

    def test_questions_editing_and_answering_cost_nothing(self):
        self.fund(1000)
        form = self.make()
        self.ask(form, 'Why?')
        self.client.post(reverse('forms:edit', args=[form.pk]), {'title': 'New', 'audience': 'public'})
        self.logout()
        self.client.post(reverse('fill', args=[form.code]), {f'q{Question.all_companies.get(form=form).pk}': 'Because'})
        self.assertEqual(self.balance(), 750)

    def test_an_exempt_company_is_not_charged(self):
        self.fund(0, is_exempt=True)
        self.assertIsNotNone(self.make())
        self.assertEqual(self.balance(), 0)

    def test_a_form_that_reached_its_cap_takes_no_more_answers(self):
        form = self.make()
        q = self.ask(form, 'Why?')
        self.logout()
        with override_settings(FORM_MAX_RESPONSES=2):
            for _i in range(3):
                self.client.post(reverse('fill', args=[form.code]), {f'q{q.pk}': 'x'})
            self.assertEqual(Response.all_companies.filter(form=form).count(), 2)
            self.assertContains(self.client.get(reverse('fill', args=[form.code])), 'This form is full')
            self.client.force_login(self.owner)
            self.assertContains(self.client.get(reverse('forms:detail', args=[form.pk])), 'reached the limit of 2 answers')
