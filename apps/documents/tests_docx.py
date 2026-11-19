import io
from unittest import mock

from django.test import SimpleTestCase
from docx import Document as ReadDocx
from docx.oxml.ns import qn

from . import docx_export

DESIGN = ('<style>.hd{background:#7c3aed;color:#ffffff;padding:12px;font-size:18pt;text-align:center}.box{border:1px solid #7c3aed;padding:8px}'
          '.row{display:grid;grid-template-columns:repeat(2,1fr)}th{background:#eeeeee}.price{background:#fef3c7}</style>'
          '<div dir="rtl"><div class="hd">عقد خدمات</div><p>الطرف الأول: <b>{{الطرف الأول}}</b> والطرف الثاني <span style="color:#cc0000">{{الطرف الثاني}}</span>.</p>'
          '<div class="row"><div class="box"><b>التاريخ</b><br>{{التاريخ}}</div><div class="box"><b>الرقم</b><br>{{الرقم}}</div></div>'
          '<table style="width:100%"><thead><tr><th style="width:10%">م</th><th>البند</th><th>المبلغ</th></tr></thead>'
          '<tbody><tr><td>1</td><td>تطوير موقع</td><td>1,000.00</td></tr><tr><td colspan="2"><b>الإجمالي</b></td><td class="price">1,000.00</td></tr></tbody></table>'
          '<ul><li>بند أول</li><li>بند ثان <span class="cb">{{اختيار}}</span></li></ul><hr><p style="text-align:left">English line</p></div>')
VALUES = {'الطرف الأول': 'شركة إنجاز', 'الطرف الثاني': 'السيد أحمد', 'التاريخ': '2026-11-02', 'الرقم': '1042', 'اختيار': '☑'}


def open_docx(data):
    return ReadDocx(io.BytesIO(data))


class ConverterTests(SimpleTestCase):
    def build(self, html, rtl=True):
        return open_docx(docx_export.build(html, rtl=rtl, title='T'))

    def test_a_designed_page_keeps_its_text_structure_colours_and_direction(self):
        from .safehtml import clean_html, render_design
        doc = self.build(render_design(clean_html(DESIGN), VALUES))
        text = '\n'.join(p.text for p in doc.paragraphs)
        self.assertIn('عقد خدمات', text)
        self.assertIn('شركة إنجاز', text)
        self.assertIn('• بند أول', text)
        self.assertIn('☑', text)                                         # a choice box becomes a ticked box
        self.assertIn('English line', text)
        self.assertEqual(len(doc.tables), 2)                              # the grid row of two boxes, and the items table
        items = doc.tables[1]
        self.assertEqual([c.text for c in items.rows[0].cells], ['م', 'البند', 'المبلغ'])
        self.assertEqual(items.rows[2].cells[0].text, 'الإجمالي')
        self.assertEqual(items.rows[2].cells[0]._tc.tcPr.find(qn('w:gridSpan')).get(qn('w:val')), '2')        # colspan = merged cells
        fills = {shd.get(qn('w:fill')) for shd in doc.element.body.iter(qn('w:shd'))}
        self.assertLessEqual({'7C3AED', 'EEEEEE', 'FEF3C7'}, fills)         # the header band, th and the highlighted total
        title = next(p for p in doc.paragraphs if p.text == 'عقد خدمات')
        self.assertIsNotNone(title._p.pPr.find(qn('w:bidi')))              # right to left
        self.assertEqual(title.runs[0].font.size.pt, 18)
        self.assertEqual(str(title.runs[0].font.color.rgb), 'FFFFFF')
        red = next(r for p in doc.paragraphs for r in p.runs if r.text == 'السيد أحمد')
        self.assertEqual(str(red.font.color.rgb), 'CC0000')
        english = next(p for p in doc.paragraphs if p.text == 'English line')
        self.assertEqual(english.alignment, 2)                             # "left" in a right-to-left paragraph is Word's "right" (end)

    def test_the_parts_are_in_the_order_word_requires(self):
        data = docx_export.build('<style>p{background:#eee;border:1px solid #000;text-align:center}</style><p dir="rtl"><b>x</b></p>', rtl=True)
        body = open_docx(data).element.body
        ppr = body.find(qn('w:p')).find(qn('w:pPr'))
        names = [c.tag.split('}')[1] for c in ppr]
        self.assertEqual(names, sorted(names, key=docx_export.ORDER['pPr'].index))
        rpr = body.find(qn('w:p')).find(qn('w:r')).find(qn('w:rPr'))
        names = [c.tag.split('}')[1] for c in rpr]
        self.assertEqual(names, sorted(names, key=docx_export.ORDER['rPr'].index))

    def test_scripts_styles_and_unknown_markup_never_reach_the_file(self):
        doc = self.build('<style>a{color:red}</style><script>alert(1)</script><p>Hello <unknown>there</unknown></p>', rtl=False)
        self.assertEqual('\n'.join(p.text for p in doc.paragraphs).strip(), 'Hello there')

    def test_a_flex_row_becomes_columns_and_a_bordered_box_is_kept(self):
        doc = self.build('<div style="display:flex"><div>One</div><div>Two</div><div>Three</div></div>'
                         '<div style="border:2px solid #333;background:#ffeecc"><p>Boxed</p></div>', rtl=False)
        self.assertEqual([c.text for c in doc.tables[0].rows[0].cells], ['One', 'Two', 'Three'])
        self.assertEqual(doc.tables[1].cell(0, 0).text, 'Boxed')

    def test_css_matching_and_units(self):
        self.assertEqual(docx_export.length_pt('16px'), 12)
        self.assertEqual(docx_export.length_pt('2em', 10), 20)
        self.assertEqual(docx_export.color_hex('rgb(255, 0, 128)'), 'FF0080')
        self.assertEqual(docx_export.color_hex('#abc'), 'AABBCC')
        self.assertEqual(docx_export.color_hex('rgba(0,0,0,0)'), '')
        self.assertEqual(docx_export.first_color('1px solid #123456'), '123456')
