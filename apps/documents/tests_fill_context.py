from django.test import SimpleTestCase

from . import generate


class ContextTextTests(SimpleTestCase):
    def test_the_words_around_each_blank_are_kept_and_the_styles_are_not(self):
        text = generate._context_text('<style>.a{color:red}</style><div><p>Sayın {{ad soyad}},</p><table><tr><td>{{tutar}} TL</td></tr></table></div>')
        self.assertEqual(text, 'Sayın {{ad soyad}},\n{{tutar}} TL')
        self.assertLessEqual(len(generate._context_text('x ' * 10000)), 3500)
