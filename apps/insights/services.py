"""Read how published posts performed, and turn it into what the planner and the reports need.

`collect` asks Meta for the numbers of a company's recent published posts. The aggregation
helpers (`summarize`, `best_slots`, `performance_block`) work only on the stored rows, so they
are cheap and need no network.
"""
import datetime
import logging
from collections import defaultdict

from django.utils import timezone

from apps.content.models import Post
from apps.social import meta
from apps.social.meta import MetaError
from apps.social.models import SocialAccount

from .models import PostInsight

logger = logging.getLogger(__name__)

WINDOW_DAYS = 45  # posts older than this are no longer re-read
REFRESH_AFTER = datetime.timedelta(hours=6)
MIN_SAMPLE = 3  # fewer posts than this and a "best time" would be noise


def collect(company, now=None):
    """Fetch insights for the company's recent published posts. Returns (rows updated, problems)."""
    now = now or timezone.now()
    accounts = {a.platform: a for a in SocialAccount.objects.filter(company=company)
                if a.platform in (SocialAccount.Platform.FACEBOOK, SocialAccount.Platform.INSTAGRAM)}
    if not accounts:
        return 0, []
    posts = Post.objects.filter(company=company, status=Post.Status.PUBLISHED,
                                published_at__gte=now - datetime.timedelta(days=WINDOW_DAYS))
    updated, problems = 0, []
    dead = set()  # platforms whose connection is expired: one failure is enough
    for post in posts:
        # JSON "empty" filters differ between MySQL and SQLite, so skip posts published by hand here.
        for platform, external in (post.external_ids or {}).items():
            account = accounts.get(platform)
            if account is None or platform in dead:
                continue
            row = PostInsight.objects.filter(post=post, platform=platform).first()
            if row and now - row.fetched_at < REFRESH_AFTER:
                continue
            try:
                if platform == SocialAccount.Platform.FACEBOOK:
                    stats = meta.facebook_post_stats(external, account.access_token)
                else:
                    stats = meta.instagram_media_stats(external, account.access_token, story=post.format == Post.Format.STORY)
            except MetaError as exc:
                problems.append(f'{account.get_platform_display()}: {exc}')
                if exc.expired:
                    dead.add(platform)  # the whole connection is bad; don't hammer it for every post
                continue
            PostInsight.objects.update_or_create(post=post, platform=platform, defaults=stats)
            updated += 1
    return updated, list(dict.fromkeys(problems))


def rows(company, start=None, end=None):
    """Insight rows of the company's posts published in [start, end)."""
    qs = PostInsight.objects.filter(post__company=company).select_related('post')
    if start:
        qs = qs.filter(post__published_at__gte=start)
    if end:
        qs = qs.filter(post__published_at__lt=end)
    return list(qs)


def _per_post(insights):
    """One entry per post: engagement summed over its platforms, reach summed where known."""
    posts = {}
    for row in insights:
        entry = posts.setdefault(row.post_id, {'post': row.post, 'engagement': 0, 'reach': 0, 'has_reach': False, 'platforms': []})
        entry['engagement'] += row.engagement
        if row.reach is not None:
            entry['reach'] += row.reach
            entry['has_reach'] = True
        entry['platforms'].append(row.platform)
    for entry in posts.values():
        entry['rate'] = round(entry['engagement'] * 100 / entry['reach'], 2) if entry['reach'] else None
        # Rank by rate when reach is known, else by raw engagement scaled so the two never mix in one list.
    return list(posts.values())


def _rank_key(entry):
    return (entry['rate'] if entry['rate'] is not None else -1, entry['engagement'])


def summarize(company, start, end):
    """Totals, top and bottom posts, and per-pillar / layout / format / weekday / hour breakdowns."""
    insights = rows(company, start, end)
    entries = _per_post(insights)
    totals = {
        'posts': len(entries),
        'reach': sum(e['reach'] for e in entries),
        'likes': sum(r.likes for r in insights), 'comments': sum(r.comments for r in insights),
        'shares': sum(r.shares for r in insights), 'saves': sum(r.saves for r in insights),
    }
    totals['engagement'] = totals['likes'] + totals['comments'] + totals['shares'] + totals['saves']
    totals['rate'] = round(totals['engagement'] * 100 / totals['reach'], 2) if totals['reach'] else None

    def card(entry):
        post = entry['post']
        return {'id': post.pk, 'title': post.title, 'headline': post.headline, 'pillar': post.pillar, 'template': post.template,
                'format': post.format, 'engagement': entry['engagement'], 'reach': entry['reach'] if entry['has_reach'] else None,
                'rate': entry['rate'], 'platforms': entry['platforms']}

    ranked = sorted(entries, key=_rank_key, reverse=True)
    return {
        'totals': totals,
        'top': [card(e) for e in ranked[:3]],
        'bottom': [card(e) for e in ranked[-3:][::-1]] if len(ranked) > 3 else [],
        'by_pillar': _breakdown(entries, lambda p: p.pillar or '—'),
        'by_layout': _breakdown(entries, lambda p: p.template),
        'by_format': _breakdown(entries, lambda p: p.format),
        'by_weekday': _breakdown(entries, lambda p: _local(company, p).weekday(), sort=False),
        'by_hour': _breakdown(entries, lambda p: _local(company, p).hour, sort=False),
    }


def _local(company, post):
    return (post.published_at or post.scheduled_at).astimezone(company.tzinfo)


def _breakdown(entries, key, sort=True):
    groups = defaultdict(list)
    for e in entries:
        groups[key(e['post'])].append(e)
    out = []
    for name, group in groups.items():
        engagement = sum(e['engagement'] for e in group)
        reach = sum(e['reach'] for e in group)
        out.append({'name': name, 'posts': len(group), 'engagement': engagement,
                    'avg_engagement': round(engagement / len(group), 1),
                    'rate': round(engagement * 100 / reach, 2) if reach else None})
    if sort:
        out.sort(key=lambda g: (g['rate'] if g['rate'] is not None else -1, g['avg_engagement']), reverse=True)
    else:
        out.sort(key=lambda g: g['name'])
    return out


def best_slots(company, limit=3):
    """The hours (local) when this company's posts did best: [(hour, posts, avg engagement)], best first.
    Hours with fewer than MIN_SAMPLE posts are ignored; an empty list means too little data."""
    by_hour = summarize(company, None, None)['by_hour']
    good = [g for g in by_hour if g['posts'] >= MIN_SAMPLE]
    good.sort(key=lambda g: (g['rate'] if g['rate'] is not None else -1, g['avg_engagement']), reverse=True)
    return [(g['name'], g['posts'], g['avg_engagement']) for g in good[:limit]]


def performance_block(company):
    """What the planner should know about past results, as a prompt section. Empty without data."""
    data = summarize(company, None, None)
    if data['totals']['posts'] < MIN_SAMPLE:
        return ''

    def fmt(g):
        rate = f', {g["rate"]}% engagement rate' if g['rate'] is not None else ''
        return f'- {g["name"]}: {g["posts"]} posts, {g["avg_engagement"]} avg interactions{rate}'

    lines = ['Results of this brand\'s published posts (real numbers from the platforms):']
    for title, key in (('By content pillar', 'by_pillar'), ('By design layout', 'by_layout'), ('By format', 'by_format')):
        if data[key]:
            lines += [f'{title}:', *map(fmt, data[key][:6])]
    if data['top']:
        lines += ['Best posts:', *(f'- "{c["title"]}" ({c["pillar"]}, layout {c["template"]}): {c["engagement"]} interactions' for c in data['top'])]
    if data['bottom']:
        lines += ['Weakest posts:', *(f'- "{c["title"]}" ({c["pillar"]}, layout {c["template"]}): {c["engagement"]} interactions' for c in data['bottom'])]
    slots = best_slots(company)
    if slots:
        lines.append('Best posting hours (local time): ' + ', '.join(f'{h:02d}:00 ({n} posts, {avg} avg)' for h, n, avg in slots))
    return ('\n<performance>\nUse this to do more of what worked and less of what did not, and to schedule posts at the strong hours. '
            'It is evidence about this audience, not a rule: keep the mix of content varied.\n' + '\n'.join(lines) + '\n</performance>\n')


def month_bounds(month, company):
    """Aware [start, end) datetimes of a month in the company's timezone."""
    start = datetime.datetime.combine(month, datetime.time.min, tzinfo=company.tzinfo)
    nxt = (month.replace(day=1) + datetime.timedelta(days=32)).replace(day=1)
    return start, datetime.datetime.combine(nxt, datetime.time.min, tzinfo=company.tzinfo)
