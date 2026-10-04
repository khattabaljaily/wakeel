"""Art direction for a plan's designs: make a month of posts look varied.

The AI suggests a layout, colour scheme and motif for every post, but models drift toward the
same few. `direct` takes the plan's posts in date order and keeps what the AI chose where it
varies, and swaps in the least-used choice where a post would look like its neighbours. It also
fills in whatever the AI left out or got wrong.
"""
import random

from .designs import MOTIFS, PHOTO_TEMPLATES, SCHEMES, TEMPLATES

RECENT = 3  # a layout may not return within this many posts


def _pick(options, used, recent, rng):
    """The least-used option not seen in the last few posts (ties broken at random)."""
    pool = [o for o in options if o not in recent] or list(options)
    fewest = min(used.get(o, 0) for o in pool)
    return rng.choice([o for o in pool if used.get(o, 0) == fewest])


def direct(items, *, has_photos=False, seed=None):
    """Fill and diversify `template`, `scheme`, `motif` and `variant` on each item (dicts, in posting order).

    Posts that aren't images (reels) keep their fields; they have no design to vary.
    """
    rng = random.Random(seed)
    layouts = [t for t in TEMPLATES if has_photos or t not in PHOTO_TEMPLATES]
    used = {'template': {}, 'scheme': {}, 'motif': {}}
    recent = {'template': [], 'scheme': [], 'motif': []}

    def choose(kind, value, options, window):
        keep = value in options and value not in recent[kind][-window:]
        chosen = value if keep else _pick(options, used[kind], recent[kind][-window:], rng)
        used[kind][chosen] = used[kind].get(chosen, 0) + 1
        recent[kind].append(chosen)
        return chosen

    for item in items:
        item['variant'] = rng.randint(1, 999999)
        if item.get('format') == 'reel':
            item.setdefault('scheme', '')
            item.setdefault('motif', '')
            continue
        item['template'] = choose('template', item.get('template'), layouts, RECENT)
        item['scheme'] = choose('scheme', item.get('scheme'), list(SCHEMES), 2)
        item['motif'] = choose('motif', item.get('motif'), list(MOTIFS), 2)
        # Loud and quiet layouts need the right ground: keep text legible on photo layouts.
        if item['template'] == 'photo':
            item['scheme'] = item['scheme'] if item['scheme'] in ('deep', 'dark', 'dusk', 'primary') else 'deep'
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
