from django.utils.translation import gettext_lazy as _
"""The design templates a post image can be rendered with.

Each key maps to templates/studio/designs/<key>.html. `hint` is what the AI
reads when it picks a template for a planned post.
"""

TEMPLATES = {
    'bold': {
        'name': _('جريء'),
        'hint': 'Solid brand-colour background, very large headline. Default for announcements, tips and statements.',
    },
    'gradient': {
        'name': _('متدرّج'),
        'hint': 'Brand gradient with a glass card. Good for services, features and educational posts.',
    },
    'photo': {
        'name': _('صورة كاملة'),
        'hint': 'Full-bleed photo with a dark overlay and text at the bottom. Use when a real product/team/place photo fits.',
    },
    'split': {
        'name': _('مقسوم'),
        'hint': 'Photo on top, colour panel with text below. Good for products and case studies.',
    },
    'minimal': {
        'name': _('بسيط'),
        'hint': 'Light background, clean dark typography. Good for facts, statistics and elegant messages.',
    },
    'quote': {
        'name': _('اقتباس'),
        'hint': 'Large quotation mark, centred text. Use for testimonials, quotes and values.',
    },
    'offer': {
        'name': _('عرض'),
        'hint': 'Big circular badge for a discount/offer (put the offer in `badge`). Use for promotions and launches.',
    },
}

PHOTO_TEMPLATES = ('photo', 'split')

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
