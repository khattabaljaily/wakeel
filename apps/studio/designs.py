from django.utils.translation import gettext_lazy as _
"""The building blocks a post image is composed from.

A design is four independent choices, so two posts rarely look alike:

- the layout (`TEMPLATES`, templates/studio/designs/<key>.html): where things sit;
- the colour scheme (`SCHEMES`): how the brand colours are used (see render.palette);
- the motif (`MOTIFS`): the decoration behind the text;
- the variant: a number that seeds the small variations (where the motif sits, the
  button and badge shape), so the same combination still differs from post to post.

`hint` is what the AI reads when it art-directs a planned post.
"""

TEMPLATES = {
    'bold': {
        'name': _('جريء'), 'scheme': 'primary',
        'hint': 'Very large headline on a solid colour with a bar under it. Default for announcements, tips and statements.',
    },
    'gradient': {
        'name': _('متدرّج'), 'scheme': 'gradient',
        'hint': 'Glass card over a colour wash. Good for services, features and educational posts.',
    },
    'photo': {
        'name': _('صورة كاملة'), 'scheme': 'deep',
        'hint': 'Full-bleed photo with a dark overlay and text at the bottom. Use when a real product/team/place photo fits.',
    },
    'split': {
        'name': _('مقسوم'), 'scheme': 'primary',
        'hint': 'Photo on top, colour panel with text below. Good for products and case studies.',
    },
    'minimal': {
        'name': _('بسيط'), 'scheme': 'light',
        'hint': 'Airy, clean typography with one colour corner. Good for facts, statistics and elegant messages.',
    },
    'quote': {
        'name': _('اقتباس'), 'scheme': 'deep',
        'hint': 'Large quotation mark, centred text, thin frame. Use for testimonials, quotes and values.',
    },
    'offer': {
        'name': _('عرض'), 'scheme': 'gradient',
        'hint': 'Big circular seal for a discount/offer (put the offer in `badge`). Use for promotions and launches.',
    },
    'poster': {
        'name': _('ملصق'), 'scheme': 'dark',
        'hint': 'Typographic poster: the headline fills the canvas, first word in the accent colour. Use for bold statements, slogans and short punchy ideas (headline of 2-5 words).',
    },
    'stat': {
        'name': _('رقم بارز'), 'scheme': 'primary',
        'hint': 'The `badge` is the hero, set huge (a number, a percentage, "24/7", a price), the headline explains it. Use for statistics, results, counts, prices and milestones; always give a short badge.',
    },
    'sidebar': {
        'name': _('شريط جانبي'), 'scheme': 'light',
        'hint': 'Coloured vertical band beside left-aligned text. Good for news, announcements, tips and lists of benefits.',
    },
    'diagonal': {
        'name': _('قطري'), 'scheme': 'deep',
        'hint': 'A diagonal colour slab cuts across the canvas, text below it. Energetic; good for launches, events and calls to join.',
    },
    'frame': {
        'name': _('إطار'), 'scheme': 'soft',
        'hint': 'Editorial: thin inset frame, centred logo and serif-like headline. Elegant; good for greetings, occasions, values and premium brands.',
    },
    'arch': {
        'name': _('قوس'), 'scheme': 'soft',
        'hint': 'Arch-shaped photo window above the headline. Warm and modern; good for people, products, places and testimonials. Prefers a real photo.',
    },
    'card': {
        'name': _('بطاقة'), 'scheme': 'accent',
        'hint': 'White card with a hard offset shadow and a sticker badge. Playful; good for tips, questions, polls, myths-vs-facts and engagement posts.',
    },
    'bands': {
        'name': _('أشرطة'), 'scheme': 'primary',
        'hint': 'Three stacked colour bands: logo and badge, headline, then subheadline with the button. Structured; good for schedules, services and step-by-step content.',
    },
    'spotlight': {
        'name': _('بؤرة'), 'scheme': 'dusk',
        'hint': 'A large round photo (or ringed shape) as focus, headline beside and below it. Good for products, introductions and features. Prefers a real photo.',
    },
}

# The decoration a layout gets when its post has no motif chosen (posts made before motifs existed).
DEFAULT_MOTIF = {
    'bold': 'rings', 'gradient': 'blobs', 'photo': 'none', 'split': 'dots', 'minimal': 'none', 'quote': 'arcs',
    'offer': 'rays', 'poster': 'grid', 'stat': 'dots', 'sidebar': 'none', 'diagonal': 'stripes', 'frame': 'none',
    'arch': 'sun', 'card': 'plus', 'bands': 'none', 'spotlight': 'rings',
}

# Layouts that show a photo from the media library when the post has one.
PHOTO_TEMPLATES = ('photo', 'split', 'arch', 'spotlight')

SCHEMES = {
    'primary': {'name': _('اللون الأساسي'), 'hint': 'brand primary colour background'},
    'secondary': {'name': _('اللون الثانوي'), 'hint': 'brand secondary colour background'},
    'accent': {'name': _('لون التمييز'), 'hint': 'brand accent colour background; loud and eye-catching'},
    'deep': {'name': _('داكن عميق'), 'hint': 'very deep shade of the primary colour; premium and calm'},
    'light': {'name': _('فاتح'), 'hint': 'warm off-white background with dark text; airy and clean'},
    'soft': {'name': _('ناعم'), 'hint': 'pale tint of the primary colour; friendly and soft'},
    'gradient': {'name': _('تدرّج'), 'hint': 'primary-to-secondary gradient; modern'},
    'dusk': {'name': _('غروب'), 'hint': 'deep-to-primary gradient; moody and rich'},
    'dark': {'name': _('أسود'), 'hint': 'near-black background; bold and dramatic, colours pop'},
}

MOTIFS = {
    'none': {'name': _('بلا زخرفة'), 'hint': 'no decoration; maximum calm'},
    'dots': {'name': _('نقاط'), 'hint': 'fading dot grid'},
    'rings': {'name': _('حلقات'), 'hint': 'large concentric rings'},
    'blobs': {'name': _('بقع لونية'), 'hint': 'soft blurred colour blobs'},
    'waves': {'name': _('موجات'), 'hint': 'flowing waves along an edge'},
    'grid': {'name': _('شبكة'), 'hint': 'fine technical grid'},
    'rays': {'name': _('أشعة'), 'hint': 'sunburst rays'},
    'stripes': {'name': _('خطوط مائلة'), 'hint': 'diagonal stripes'},
    'arcs': {'name': _('أقواس'), 'hint': 'quarter-circle arcs in the corners'},
    'confetti': {'name': _('قصاصات'), 'hint': 'scattered confetti; festive'},
    'plus': {'name': _('علامات زائد'), 'hint': 'pattern of small plus signs'},
    'sun': {'name': _('شمس'), 'hint': 'a large half-sun with halo'},
}

SIZES = {
    'square': (1080, 1080),
    'portrait': (1080, 1350),
    'story': (1080, 1920),
}

# Font key -> CSS family name, as declared in static/fonts/fonts.css.
FONT_FAMILIES = {
    'cairo': 'Cairo',
    'tajawal': 'Tajawal',
    'almarai': 'Almarai',
    'plex': 'IBM Plex Sans Arabic',
    'readex': 'Readex Pro',
    'messiri': 'El Messiri',
    'kufi': 'Noto Kufi Arabic',
    'amiri': 'Amiri',
}


def template_choices():
    return [(key, t['name']) for key, t in TEMPLATES.items()]


def scheme_choices():
    return [('', _('تلقائي'))] + [(key, s['name']) for key, s in SCHEMES.items()]


def motif_choices():
    return [('', _('تلقائي'))] + [(key, m['name']) for key, m in MOTIFS.items()]
