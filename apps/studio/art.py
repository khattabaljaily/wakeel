"""Art direction for a plan's designs: a layout that serves each post's content, and a month that doesn't repeat itself.

The AI suggests a layout and a colour scheme for every post. `direct` takes the plan's posts in date order and:

1. keeps the AI's layout when the post has what that layout needs (a figure for `figure`, list lines for `steps`...),
   and otherwise reads the content and picks the layout that fits it;
2. keeps a layout from returning within a few posts, swapping in another one the content also suits;
3. gives each layout only the grounds it looks good on, and rotates them so neighbours differ.

Legacy layouts (the 16 older ones) are no longer chosen; posts that already use them keep rendering unchanged.
"""
import random
import re

from .designs import PHOTO_TEMPLATES, SCHEMES, V2_LAYOUTS
from .v2 import MOCKS, figure_parts, has_word, split_points

STRONG = ('greeting', 'promo', 'ask')  # content signals clear enough to override the AI's layout
RECENT = 2  # a layout may not return within this many posts

# The grounds each layout is good on, best first (names are colour schemes; see v2.SCHEME_GROUND).
LAYOUT_SCHEMES = {
    'statement': ('dark', 'light', 'primary', 'deep', 'soft'),
    'display': ('dark', 'primary', 'light', 'deep'),
    'figure': ('light', 'soft', 'primary', 'dark'),
    'showcase': ('deep', 'dark', 'soft', 'light'),
    'greeting': ('deep', 'dark'),
    'steps': ('light', 'soft', 'dark', 'primary'),
    'ask': ('primary', 'light', 'deep', 'soft'),
    'testimonial': ('soft', 'light', 'deep', 'primary'),
    'cover': ('dark',),
    'promo': ('primary', 'dark', 'deep'),
}

OCCASION = 'جمعة عيد رمضان مبارك تهنئة|كل عام|اليوم الوطني|المولد النبوي|الإسراء|رأس السنة|الأضحى|الفطر eid ramadan'
OFFER = 'خصم عرض تخفيض مجاني مجانا مجاناً حملة offer discount sale free'
REVIEW = 'رأي رأيهم عميل عملاؤنا عملائنا شهادة تجربة تقييم testimonial review'


def _text(item):
    return ' '.join(str(item.get(k) or '') for k in ('headline', 'subheadline', 'title', 'pillar', 'badge')).lower()


def _has_any(text, words):
    if '|' in words:  # phrases
        phrases = [p for p in words.split('|')]
        singles = phrases[0].split() + phrases[-1].split()
        return any(p in text for p in phrases[1:-1]) or has_word(text, ' '.join(singles))
    return has_word(text, words)


def _has_figure(item):
    return bool(re.search(r'\d', str(item.get('badge') or '')))


def supports(layout, item, has_photos):
    """Whether the post has what the layout needs to look right."""
    if layout == 'figure':
        return bool(figure_parts(item.get('badge', ''), item.get('headline', ''))[0])
    if layout == 'promo':
        return bool(item.get('badge'))
    if layout == 'steps':
        return len(split_points(item.get('subheadline', ''))) >= 2
    if layout == 'ask':
        return str(item.get('headline') or '').strip().endswith(('؟', '?'))
    if layout == 'cover':
        return has_photos
    return True


def infer(item, has_photos):
    """The layout the content points to, or '' when it is just a message (statement)."""
    text = _text(item)
    headline = str(item.get('headline') or '')
    if _has_any(text, OCCASION) and not _has_any(text, OFFER):
        return 'greeting'
    if item.get('badge') and (_has_any(text, OFFER) or '%' in str(item.get('badge'))):
        return 'promo'
    if split_points(item.get('subheadline', '')):
        return 'ask' if headline.strip().endswith(('؟', '?')) else 'steps'
    if headline.strip().endswith(('؟', '?')):
        return 'ask'
    if _has_any(text, REVIEW):
        return 'testimonial'
    if _has_figure(item):
        return 'figure'
    if any(_has_any(text, words) for _kind, words in MOCKS) or any(str(v).startswith('device-') for v in item.get('vectors') or []):
        return 'showcase'
    return ''


def _pick(options, used, recent, rng):
    """The least-used option not seen in the last few posts (ties broken at random)."""
    pool = [o for o in options if o not in recent] or list(options)
    fewest = min(used.get(o, 0) for o in pool)
    return rng.choice([o for o in pool if used.get(o, 0) == fewest])


def direct(items, *, has_photos=False, seed=None):
    """Fill and diversify `template`, `scheme` and `variant` on each item (dicts, in posting order).

    Posts that aren't images (reels) keep their fields; they have no design to vary.
    """
    rng = random.Random(seed)
    used = {'template': {}, 'scheme': {}}
    recent = {'template': [], 'scheme': []}

    for item in items:
        item['variant'] = rng.randint(1, 999999)
        if item.get('format') == 'reel':
            item.setdefault('scheme', '')
            item.setdefault('motif', '')
            continue
        hint = infer(item, has_photos)
        layout = item.get('template')
        if layout not in V2_LAYOUTS or not supports(layout, item, has_photos):
            layout = hint or 'statement'
        elif hint and (layout == 'statement' or hint in STRONG and layout != hint):
            layout = hint  # the AI fell back on the generic layout, or missed a clear signal in the content
        if layout in recent['template'][-RECENT:]:
            # Another layout this content suits, else the least-used generic one; a repeat is the last resort.
            fits = [t for t in V2_LAYOUTS if t not in PHOTO_TEMPLATES and t not in ('greeting', 'testimonial', 'showcase') and supports(t, item, has_photos)]
            fits = [t for t in fits if t not in recent['template'][-RECENT:]]
            if hint in fits:
                fits = [hint]
            if fits:
                layout = _pick(fits, used['template'], [], rng)
        used['template'][layout] = used['template'].get(layout, 0) + 1
        recent['template'].append(layout)

        allowed = [s for s in LAYOUT_SCHEMES[layout] if s in SCHEMES]
        scheme = item.get('scheme')
        if scheme not in allowed or scheme in recent['scheme'][-1:]:
            scheme = _pick(allowed, used['scheme'], recent['scheme'][-2:], rng)
        used['scheme'][scheme] = used['scheme'].get(scheme, 0) + 1
        recent['scheme'].append(scheme)
        item['template'], item['scheme'], item['motif'] = layout, scheme, ''
    return items


def assign_backgrounds(posts, assets):
    """Give photo layouts a photo from the media library, cycling so neighbours differ."""
    assets = list(assets)
    if not assets:
        return
    n = 0
    for post in posts:
        if post.template in PHOTO_TEMPLATES and not post.background_id:
            post.background = assets[n % len(assets)]
            n += 1
