from django.test import TestCase

from .models import Document


class AddresseeTests(TestCase):
    def test_the_addressee_is_printed_with_to_unless_it_already_says_so(self):
        from django.utils import translation
        cases = {'من يهمه الأمر': 'إلى من يهمه الأمر', 'السادة / بنك الخرطوم': 'السادة / بنك الخرطوم',
                 'إلى من يهمه الأمر': 'إلى من يهمه الأمر', '': ''}
        with translation.override('ar'):
            for typed, printed in cases.items():
                self.assertEqual(Document(recipient=typed).addressed_to, printed, typed)
        with translation.override('en'):
            self.assertEqual(Document(recipient='Bank of Khartoum').addressed_to, 'To Bank of Khartoum')
            self.assertEqual(Document(recipient='Dear Sirs').addressed_to, 'Dear Sirs')


class DesignMarkupTests(TestCase):
    """The layout marks the AI is taught to use: forms, item tables, totals, plain blocks, titles, notes, choices."""

    def html(self, text):
        from .templatetags.doc_tags import document_body
        return str(document_body(text))

    def test_a_form_table_has_its_labels_in_the_odd_columns_and_a_four_column_one_is_marked(self):
        two = self.html('Name | Omar\nCity | Doha')
        self.assertIn('class="grid kv"', two)
        four = self.html('No. | 1 | Date | 2026-11-01')
        self.assertIn('class="grid kv four"', four)

    def test_an_item_table_has_a_header_and_numbers_are_aligned_to_the_end(self):
        html = self.html('Item | Qty | Price\n---\nPen | 3 | 1,200.50')
        self.assertIn('<thead>', html)
        self.assertNotIn(' kv', html)
        self.assertIn('<td class="num">3</td>', html)
        self.assertIn('<td class="num">1,200.50</td>', html)
        self.assertIn('<td>Pen</td>', html)

    def test_narrow_and_plain_tables_title_and_note(self):
        self.assertIn('class="grid narrow kv"', self.html('@narrow\nTotal | 10'))
        self.assertIn('class="grid plain kv four"', self.html('@plain\nName | A | Signature | '))
        html = self.html('## Sales invoice\n\n> Payment within 30 days.')
        self.assertIn('<h2 class="title">Sales invoice</h2>', html)
        self.assertIn('<p class="note">Payment within 30 days.</p>', html)

    def test_choices_on_one_line_stay_together_and_a_single_blank_cell_is_not_a_number(self):
        html = self.html('[ ] Full time [x] Part time [ ] Remote')
        self.assertIn('<p class="choices">', html)
        self.assertEqual(html.count('class="box"'), 3)
        self.assertNotIn('class="num"', self.html('Name | {{customer}}'))

    def test_a_body_with_its_own_title_hides_the_subject_above_it(self):
        from .templatetags.doc_tags import has_title
        self.assertTrue(has_title('No. | 1\n\n## Offer\n\ntext'))
        self.assertFalse(has_title('# Section only\n\ntext'))



class SafeHtmlTests(TestCase):
    """A designed page is written by the AI from files and instructions we do not control: only a small safe part of
    HTML and CSS survives."""

    def clean(self, source):
        from .safehtml import clean_html
        return clean_html(source)

    def test_scripts_frames_links_images_and_handlers_are_gone_but_the_text_stays(self):
        html = self.clean('<div onclick="x()" class="a b">Hi <script>alert(1)</script><img src="http://evil/x.png"><a href="http://evil">link</a>'
                          '<iframe src="http://evil"></iframe><svg><circle/></svg><b>bold</b></div>')
        for bad in ('script', 'onclick', 'img', 'href', 'http', 'iframe', 'svg', 'alert'):
            self.assertNotIn(bad, html)
        self.assertIn('<div class="a b">Hi ', html)
        self.assertIn('<b>bold</b>', html)
        self.assertIn('link', html)                                              # the text of a dropped tag is kept

    def test_css_is_scoped_and_only_safe_properties_and_values_survive(self):
        css = self.clean('<style>body{color:#123;font-family:Evil} h1, .x{background:url(http://evil/a.png);color:red;border:1px solid #ccc}'
                         '@import url(http://evil/x.css); @media print{.y{color:blue}} .z{position:fixed;top:0;display:flex;behavior:x}</style><p>t</p>')
        self.assertIn('.dh{color:#123;font-family:Almohanad, sans-serif}', css)
        self.assertIn('.dh h1, .dh .x{color:red;border:1px solid #ccc}', css)
        self.assertIn('.dh .z{display:flex}', css)
        for bad in ('evil', 'url', '@import', '@media', 'position', 'behavior', 'blue'):
            self.assertNotIn(bad, css)

    def test_inline_styles_are_cleaned_and_markup_is_escaped(self):
        html = self.clean('<td style="color:red; background:url(javascript:x); padding:4px" colspan="2" data-x="1" colspan2="3">&lt;b&gt; &amp; {{name}}</td>')
        self.assertIn('style="color:red;padding:4px"', html)
        self.assertIn('colspan="2"', html)
        self.assertNotIn('data-x', html)
        self.assertIn('&lt;b&gt; &amp; {{name}}', html)

    def test_code_fences_are_dropped_and_an_empty_result_is_empty(self):
        self.assertEqual(self.clean('```html\n<p>x</p>\n```'), '<p>x</p>')
        self.assertEqual(self.clean('<script>x</script>'), '')
        self.assertEqual(self.clean(''), '')

    def test_a_design_is_filled_with_escaped_values_dotted_lines_and_marked_on_a_template(self):
        from .safehtml import blank_names, render_design
        design = '<p>Dear {{name}}, you owe {{amount}} &amp; {{name}}.</p>'
        self.assertEqual(blank_names(design), ['name', 'amount'])
        self.assertEqual(render_design(design, {'name': '<b>Omar</b>', 'amount': ''}),
                         '<p>Dear <bdi>&lt;b&gt;Omar&lt;/b&gt;</bdi>, you owe .......... &amp; <bdi>&lt;b&gt;Omar&lt;/b&gt;</bdi>.</p>')
        self.assertIn('<mark class="blank">amount</mark>', render_design(design, marks=True))

    def test_a_choice_box_the_design_draws_gets_a_tick_or_nothing_never_a_second_box(self):
        from .safehtml import render_design
        design = '<p><span class="cb">{{yes}}</span> Full <span class="cb">{{no}}</span> Part <span class="cb x">{{unknown}}</span> End</p>'
        html = render_design(design, {'yes': '☑', 'no': '☐'})
        self.assertIn('<span class="cb">&#10003;</span>', html)
        self.assertIn('<span class="cb">&nbsp;</span> Part', html)
        self.assertIn('<span class="cb x">&nbsp;</span> End', html)                         # empty: no dotted line in a box
        self.assertNotIn('☐', html)
        self.assertNotIn('..........', html)
        self.assertIn('<mark class="blank">yes</mark>', render_design(design, marks=True))      # a template shows the field

    def test_cleaning_a_clean_page_changes_nothing_and_the_models_only_keep_safe_designs(self):
        once = self.clean('<style>h1{color:red}</style><h1>T {{a}}</h1>')
        self.assertEqual(self.clean(once), once)
        from apps.content.tests import make_company
        from .models import DocumentTemplate
        company = make_company('X')
        template = DocumentTemplate.all_companies.create(company=company, name='T',
                                                         html='<p onclick="x()">Hi {{a}}</p><script>bad()</script>')
        self.assertEqual(template.html, '<p>Hi {{a}}</p>')
        document = Document(company=company, title='T')
        document.design = '<img src=http://evil/x><p>ok {{a}}</p>'
        self.assertEqual(document.design, '<p>ok {{a}}</p>')


class MoneyFormatTests(TestCase):
    def test_money_values_of_a_document_are_written_1000_00_and_other_values_are_left_alone(self):
        from .generate import normalize_money as money
        self.assertEqual(money('الراتب الأساسي الشهري', '1200 دولار'), '1,200.00 دولار')
        self.assertEqual(money('Total amount', '1500'), '1,500.00')
        self.assertEqual(money('إجمالي الراتب', '1,234,567.5 USD'), '1,234,567.50 USD')
        self.assertEqual(money('سعر الوحدة', '99.999'), '99.999')                  # three decimals: not a price format, left as it is
        self.assertEqual(money('رقم العرض', '045'), '045')                      # a number, not money
        self.assertEqual(money('المبلغ كتابةً', 'ألف دولار'), 'ألف دولار')       # in words
        self.assertEqual(money('نسبة الضريبة', '15'), '15')                      # a percentage
        self.assertEqual(money('تاريخ الإصدار', '2026-11-02'), '2026-11-02')
        self.assertEqual(money('المبلغ', 'بالاتفاق'), 'بالاتفاق')
