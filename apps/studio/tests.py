import types
from itertools import product

from django.test import SimpleTestCase, TestCase
from django.urls import reverse

from apps.content.models import Post
from apps.content.tests import make_company, make_user

from . import art
from .designs import DEFAULT_MOTIF, MOTIFS, PHOTO_TEMPLATES, SCHEMES, SIZES, TEMPLATES, V2_LAYOUTS
from .render import contrast, design_context, palette, post_fields, render_html, variation


def fake_company(**kwargs):
    return types.SimpleNamespace(**{
        'name': 'شركة', 'logo': None, 'website': 'https://x.example', 'instagram_handle': 'x', 'phone': '123',
        'primary_color': '#1f5fbf', 'secondary_color': '#0ea5a4', 'accent_color': '#f59e0b',
        'heading_font': 'cairo', 'body_font': 'tajawal', **kwargs})


COPY = {'headline': 'نظام متكامل لإدارة عقاراتك', 'subheadline': 'تابع كل شيء', 'cta': 'جرّب', 'badge': '20%',
        'background': None, 'variant': 5}


class PaletteTests(SimpleTestCase):
    def test_accent_always_stands_out_from_the_ground(self):
        # Brand colours that clash: accent nearly equal to primary.
        for scheme in SCHEMES:
            k = palette(scheme, '#1f5fbf', '#2060c0', '#2161c1')
            self.assertGreaterEqual(contrast(k['bg_base'], k['ac']), 1.5, scheme)
            self.assertGreaterEqual(contrast(k['bg_base'], k['fg']), 4.5, scheme)

    def test_every_scheme_is_defined_for_extreme_brand_colours(self):
        for colours in (('#000000', '#000000', '#000000'), ('#ffffff', '#ffffff', '#ffffff'), ('#ff0000', '#00ff00', '#0000ff')):
            for scheme in SCHEMES:
                k = palette(scheme, *colours)
                self.assertTrue(k['bg'] and k['fg'] and k['ac'], (scheme, colours))

    def test_variation_is_deterministic_and_differs_by_seed(self):
        self.assertEqual(variation(7), variation(7))
        self.assertNotEqual([variation(n) for n in range(10)], [variation(0)] * 10)


class RenderTemplatesTests(SimpleTestCase):
    def test_every_layout_renders_in_every_size_scheme_and_motif(self):
        company = fake_company()
        for template, size in product(TEMPLATES, SIZES):
            for scheme, motif in zip([''] + list(SCHEMES), [''] + list(MOTIFS)):
                html = render_html(company, {**COPY, 'template': template, 'size': size, 'scheme': scheme, 'motif': motif})
                self.assertIn(f'{"l" if template in V2_LAYOUTS else "t"}-{template}', html)
                self.assertIn(f'size-{size}', html)

    def test_defaults_come_from_the_layout(self):
        ctx = design_context(fake_company(), {**COPY, 'template': 'offer', 'size': 'square', 'scheme': '', 'motif': ''})
        self.assertEqual(ctx['scheme'], TEMPLATES['offer']['scheme'])
        self.assertEqual(ctx['motif'], DEFAULT_MOTIF['offer'])

    def test_unknown_scheme_and_motif_fall_back(self):
        ctx = design_context(fake_company(), {**COPY, 'template': 'bold', 'size': 'square', 'scheme': 'neon', 'motif': 'lasers'})
        self.assertEqual(ctx['scheme'], 'primary')
        self.assertEqual(ctx['motif'], DEFAULT_MOTIF['bold'])

    def test_every_layout_has_a_default_motif(self):
        self.assertEqual(set(DEFAULT_MOTIF), set(TEMPLATES) - set(V2_LAYOUTS))  # the v2 layouts take their ornament from the brand

    def test_poster_splits_the_first_word(self):
        ctx = design_context(fake_company(), {**COPY, 'template': 'poster', 'size': 'square', 'scheme': '', 'motif': ''})
        self.assertEqual(ctx['headline_first'], 'نظام')
        self.assertTrue(ctx['headline_rest'].startswith('متكامل'))


def plan_items(n, **extra):
    return [{'template': 'statement', 'scheme': 'dark', 'format': 'image', 'headline': f'فكرة {i}', **extra} for i in range(n)]


MIXED = [
    {'headline': 'ست خدمات وشريك تقني واحد', 'badge': 'إنجاز'},
    {'headline': 'ثلاث خطوات لبدء مشروعك', 'subheadline': 'نفهم فكرتك\nنصمم ونبني\nنطلق وندعم'},
    {'headline': 'جمعة مباركة', 'title': 'جمعة'},
    {'headline': 'ما أكبر تحدٍّ يواجه عملك؟', 'subheadline': 'المخزون\nالمواعيد'},
    {'headline': 'خصم خاص على المواقع', 'badge': '30%'},
    {'headline': 'خبرة تقف خلف كل مشروع', 'badge': '9 سنوات'},
    {'headline': 'مخزونك تحت السيطرة', 'subheadline': 'Enjaz IMS لإدارة المخزون'},
    {'headline': 'رأي عميلنا: خدمة ممتازة', 'subheadline': 'أحمد — صيدلي'},
]


class ArtDirectionTests(SimpleTestCase):
    def test_layout_follows_the_content(self):
        items = [{**m, 'template': 'statement', 'format': 'image'} for m in MIXED]
        out = art.direct(items, has_photos=False, seed=1)
        self.assertEqual([i['template'] for i in out],
                         ['statement', 'steps', 'greeting', 'ask', 'promo', 'figure', 'showcase', 'testimonial'])

    def test_a_layout_is_not_kept_when_the_post_lacks_what_it_needs(self):
        out = art.direct([{'template': 'figure', 'headline': 'نص بلا رقم', 'format': 'image'},
                          {'template': 'steps', 'headline': 'قائمة', 'subheadline': 'سطر واحد', 'format': 'image'},
                          {'template': 'ask', 'headline': 'عبارة عادية', 'format': 'image'}], seed=2)
        self.assertEqual([i['template'] for i in out], ['statement', 'display', 'statement'])

    def test_a_month_of_plain_messages_is_varied(self):
        items = art.direct(plan_items(16), has_photos=False, seed=1)
        layouts = [i['template'] for i in items]
        self.assertGreaterEqual(len(set(layouts)), 2)
        for a, b in zip(layouts, layouts[1:]):
            self.assertNotEqual(a, b)
        self.assertGreaterEqual(len({i['scheme'] for i in items}), 4)
        self.assertEqual(len({i['variant'] for i in items}), 16)

    def test_every_layout_gets_a_ground_it_is_designed_for(self):
        for layout, schemes in art.LAYOUT_SCHEMES.items():
            self.assertIn(layout, V2_LAYOUTS)
            self.assertTrue(set(schemes) <= set(SCHEMES), layout)
        out = art.direct([{**m, 'template': 'statement', 'format': 'image'} for m in MIXED] * 3, seed=3)
        for i in out:
            self.assertIn(i['scheme'], art.LAYOUT_SCHEMES[i['template']])

    def test_legacy_and_invalid_layouts_are_replaced(self):
        out = art.direct([{'template': 'neon', 'scheme': 'x', 'format': 'image', 'headline': 'م'},
                          {'template': 'bold', 'scheme': '', 'format': 'image', 'headline': 'م'}], seed=2)
        for i in out:
            self.assertIn(i['template'], V2_LAYOUTS)
            self.assertIn(i['scheme'], SCHEMES)
            self.assertEqual(i['motif'], '')

    def test_photo_layouts_are_avoided_without_photos(self):
        out = art.direct(plan_items(30, template='cover'), has_photos=False, seed=4)
        self.assertFalse({i['template'] for i in out} & set(PHOTO_TEMPLATES))

    def test_cover_is_kept_when_photos_exist(self):
        self.assertEqual(art.direct([{'template': 'cover', 'headline': 'م', 'format': 'image'}], has_photos=True, seed=4)[0]['template'], 'cover')

    def test_reels_keep_their_fields(self):
        out = art.direct([{'format': 'reel', 'template': 'bold'}], seed=5)[0]
        self.assertEqual(out['template'], 'bold')
        self.assertEqual((out['scheme'], out['motif']), ('', ''))

    def test_same_seed_gives_same_result(self):
        self.assertEqual(art.direct(plan_items(12), seed=9), art.direct(plan_items(12), seed=9))


class V2StyleTests(SimpleTestCase):
    def test_dark_grounds_are_neutral_not_muddy_for_warm_brands(self):
        from . import style
        pal = style.palette('#E8A13A', '#3A3D40', '#E8A13A')  # amber: darkening it gives brown
        for key in ('ink', 'deep'):
            self.assertLessEqual(style._hls(pal[key])[2], 0.25, key)  # low saturation
        self.assertGreaterEqual(style.contrast(pal['brand_on_ink'], pal['ink']), 4.5)
        self.assertGreaterEqual(style.contrast(pal['brand_on_paper'], pal['paper']), 3)

    def test_shape_is_stable_per_brand_and_differs_between_brands(self):
        from . import style
        a = fake_company(name='إنجاز')
        self.assertEqual(style.shape(a), style.shape(a))
        shapes = {tuple(style.shape(fake_company(name=f'شركة {n}', primary_color=f'#{n * 7919 % 0xffffff:06x}')).items()) for n in range(12)}
        self.assertGreaterEqual(len(shapes), 6)

    def test_figure_parts(self):
        from .v2 import figure_parts
        self.assertEqual(figure_parts('99.9%'), ('99.9', '%'))
        self.assertEqual(figure_parts('9 سنوات'), ('9', 'سنوات'))
        self.assertEqual(figure_parts('24/7'), ('24/7', ''))
        self.assertEqual(figure_parts('+500'), ('+500', ''))
        self.assertEqual(figure_parts('', 'أكثر من 120 عميلاً')[0], '120')
        self.assertEqual(figure_parts('جديد', 'بلا أرقام'), ('', ''))

    def test_points_need_at_least_two_lines(self):
        from .v2 import split_points
        self.assertEqual(split_points('أ\nب\nج'), ['أ', 'ب', 'ج'])
        self.assertEqual(split_points('أ | ب'), ['أ', 'ب'])
        self.assertEqual(split_points('سطر واحد'), [])

    def test_mock_follows_the_topic(self):
        from .v2 import mock_kind
        self.assertEqual(mock_kind('إدارة المواعيد والحجوزات', []), 'calendar')
        self.assertEqual(mock_kind('Enjaz IMS لإدارة المخزون', []), 'list')
        self.assertEqual(mock_kind('تطبيق جوال جديد', []), 'phone')
        self.assertEqual(mock_kind('شركة ناشئة', []), 'dashboard')
        self.assertEqual(mock_kind('happy times', []), 'dashboard')  # Latin words match whole words only

    def test_headline_html_escapes_and_highlights_one_phrase(self):
        from .v2 import highlight
        html = str(highlight('خدمات <b>تقنية</b> لعملك اليوم', 3))
        self.assertNotIn('<b>', html)
        self.assertEqual(html.count('class="hl"'), 1)
        self.assertNotIn('class="hl"', str(highlight('كلمتان فقط', 3)))

    def test_every_v2_layout_renders_in_ar_and_en_with_long_text(self):
        company = fake_company()
        long_ar = 'عنوان طويل جداً يحتوي على كلمات كثيرة لاختبار الملاءمة التلقائية داخل التصميم'
        for layout, size in product(V2_LAYOUTS, SIZES):
            for headline in ('عنوان', long_ar, 'A very long English headline to test the layout'):
                sub = 'First line\nSecond line' if headline[0].isascii() else 'سطر أول\nسطر ثان'
                html = render_html(company, {**COPY, 'headline': headline, 'subheadline': sub, 'template': layout,
                                             'size': size, 'scheme': '', 'motif': ''})
                self.assertIn(f'l-{layout}', html)
                self.assertIn('dir="ltr"' if headline[0].isascii() else 'dir="rtl"', html)

    def test_every_ground_renders_for_every_v2_layout(self):
        company = fake_company(primary_color='#FFD400')  # a light brand colour is the hard case for contrast
        for layout in V2_LAYOUTS:
            for scheme in SCHEMES:
                html = render_html(company, {**COPY, 'template': layout, 'size': 'square', 'scheme': scheme})
                self.assertIn('--bg:', html)


class PreviewViewTests(TestCase):
    def setUp(self):
        self.company = make_company(primary_color='#1f5fbf')
        self.user = make_user('owner@example.com', self.company)
        self.post = Post.objects.create(company=self.company, title='م', headline='عنوان', platforms=['facebook'])
        self.client.force_login(self.user)

    def test_preview_takes_unsaved_design_choices(self):
        url = reverse('studio:preview', args=[self.post.pk])
        html = self.client.get(url, {'template': 'stat', 'scheme': 'dark', 'motif': 'grid', 'variant': '42', 'badge': '99%'}).content.decode()
        self.assertIn('t-stat', html)
        self.assertIn('m-grid', html)
        self.assertIn('#0f1115', html)

    def test_preview_survives_junk(self):
        url = reverse('studio:preview', args=[self.post.pk])
        response = self.client.get(url, {'template': 'zzz', 'scheme': 'zzz', 'motif': 'zzz', 'variant': 'abc'})
        self.assertEqual(response.status_code, 200)

    def test_post_fields_use_the_saved_variant(self):
        self.post.variant = 77
        self.assertEqual(post_fields(self.post)['variant'], 77)
        self.post.variant = 0
        self.assertEqual(post_fields(self.post)['variant'], self.post.pk)


class VectorTests(SimpleTestCase):
    def test_every_vector_has_a_drawing(self):
        from .vectors import VECTORS, drawings
        self.assertEqual(set(VECTORS), set(drawings()))

    def test_guess_reads_arabic_with_prefixes_and_suffixes(self):
        from .vectors import guess
        self.assertEqual(guess('تهنئة بمناسبة اليوم الوطني', 'كل عام ووطننا بخير')[0], 'flag')
        self.assertEqual(guess('رمضان كريم')[0], 'moon-stars')
        self.assertIn('building-warehouse', guess('نظام إدارة المخزون والمبيعات'))
        self.assertEqual(guess('شقق للإيجار في الدوحة')[:2], ['home', 'key'])
        self.assertEqual(len(guess('')), 3)  # nothing matches: the fallback set

    def test_chosen_vectors_win_and_bad_keys_are_dropped(self):
        from .vectors import for_post
        self.assertEqual([k for k, _svg in for_post(['rocket', 'nope', 'gift'], 'رمضان')], ['rocket', 'gift'])
        self.assertEqual(for_post([], 'رمضان كريم')[0][0], 'moon-stars')

    def test_art_only_on_the_general_layouts(self):
        from .designs import ART_TEMPLATES
        company = fake_company()
        for template in TEMPLATES:
            html = render_html(company, {**COPY, 'template': template, 'size': 'square', 'scheme': '', 'motif': '', 'vectors': ['rocket']})
            self.assertEqual('<div class="art"' in html, template in ART_TEMPLATES, template)


class EditorVectorTests(TestCase):
    def setUp(self):
        self.company = make_company()
        self.user = make_user('e@example.com', self.company)
        self.post = Post.objects.create(company=self.company, title='م', headline='عنوان', platforms=['facebook'])
        self.client.force_login(self.user)

    def save(self, **extra):
        data = {'title': 'م', 'platforms': ['facebook'], 'format': 'image', 'headline': 'عنوان', 'template': 'bold', 'size': 'square', **extra}
        return self.client.post(reverse('content:post_edit', args=[self.post.pk]), data)

    def test_editor_saves_up_to_three_vectors(self):
        self.assertEqual(self.save(vectors=['rocket', 'gift']).status_code, 200)
        self.post.refresh_from_db()
        self.assertEqual(self.post.vectors, ['rocket', 'gift'])
        self.assertEqual(self.save(vectors=['rocket', 'gift', 'star', 'heart']).status_code, 400)
        self.assertEqual(self.save(vectors=['not-a-vector']).status_code, 400)

    def test_preview_takes_vectors(self):
        html = self.client.get(reverse('studio:preview', args=[self.post.pk]), {'vectors': 'rocket,gift'}).content.decode()
        self.assertIn('<div class="art"', html)
