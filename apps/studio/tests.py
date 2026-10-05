import types
from itertools import product

from django.test import SimpleTestCase, TestCase
from django.urls import reverse

from apps.content.models import Post
from apps.content.tests import make_company, make_user

from . import art
from .designs import DEFAULT_MOTIF, MOTIFS, PHOTO_TEMPLATES, SCHEMES, SIZES, TEMPLATES
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
                self.assertIn(f't-{template}', html)
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
        self.assertEqual(set(DEFAULT_MOTIF), set(TEMPLATES))

    def test_poster_splits_the_first_word(self):
        ctx = design_context(fake_company(), {**COPY, 'template': 'poster', 'size': 'square', 'scheme': '', 'motif': ''})
        self.assertEqual(ctx['headline_first'], 'نظام')
        self.assertTrue(ctx['headline_rest'].startswith('متكامل'))


def plan_items(n, **extra):
    return [{'template': 'bold', 'scheme': 'primary', 'motif': 'dots', 'format': 'image', **extra} for _ in range(n)]


class ArtDirectionTests(SimpleTestCase):
    def test_a_month_of_identical_choices_is_varied(self):
        items = art.direct(plan_items(16), has_photos=True, seed=1)
        layouts = [i['template'] for i in items]
        self.assertGreaterEqual(len(set(layouts)), 8)
        for a, b in zip(layouts, layouts[1:]):
            self.assertNotEqual(a, b)
        for window in zip(layouts, layouts[1:], layouts[2:], layouts[3:]):
            self.assertEqual(len(set(window)), 4, window)
        self.assertGreaterEqual(len({i['scheme'] for i in items}), 5)
        self.assertGreaterEqual(len({i['motif'] for i in items}), 6)
        self.assertEqual(len({i['variant'] for i in items}), 16)

    def test_good_choices_are_kept(self):
        items = [{'template': t, 'scheme': s, 'motif': m, 'format': 'image'}
                 for t, s, m in (('stat', 'dark', 'grid'), ('quote', 'deep', 'arcs'), ('card', 'accent', 'plus'))]
        out = art.direct(items, has_photos=True, seed=3)
        self.assertEqual([(i['template'], i['scheme'], i['motif']) for i in out],
                         [('stat', 'dark', 'grid'), ('quote', 'deep', 'arcs'), ('card', 'accent', 'plus')])

    def test_invalid_choices_are_replaced(self):
        out = art.direct([{'template': 'neon', 'scheme': 'x', 'motif': '', 'format': 'image'}], seed=2)[0]
        self.assertIn(out['template'], TEMPLATES)
        self.assertIn(out['scheme'], SCHEMES)
        self.assertIn(out['motif'], MOTIFS)

    def test_photo_layouts_are_avoided_without_photos(self):
        out = art.direct(plan_items(30, template='photo'), has_photos=False, seed=4)
        self.assertFalse({i['template'] for i in out} & set(PHOTO_TEMPLATES))

    def test_reels_keep_their_fields(self):
        out = art.direct([{'format': 'reel', 'template': 'bold'}], seed=5)[0]
        self.assertEqual(out['template'], 'bold')
        self.assertEqual((out['scheme'], out['motif']), ('', ''))

    def test_same_seed_gives_same_result(self):
        self.assertEqual(art.direct(plan_items(12), seed=9), art.direct(plan_items(12), seed=9))


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
