"""Posts made from other posts: language and dialect versions, and evergreen reposts.

A version keeps the idea, the design and the date and rewrites every text in another language or
dialect. A repost brings back a post that did well (or that the team marked evergreen) with fresh
wording and a fresh look, on a free day at one of the brand's best hours.
"""
import datetime
import random

from django.utils import timezone
from django.utils.translation import gettext_lazy as _

from .models import Post

VARIANTS = {
    'ar_msa': (_('العربية الفصحى'), 'clear, modern Standard Arabic (فصحى) that reads naturally on social media'),
    'ar_gulf': (_('اللهجة الخليجية'), 'the everyday Gulf Arabic spoken in Qatar, Saudi Arabia and the UAE'),
    'ar_sd': (_('اللهجة السودانية'), 'the everyday Sudanese Arabic people in Sudan use on social media'),
    'ar_eg': (_('اللهجة المصرية'), 'the everyday Egyptian Arabic people in Egypt use on social media'),
    'ar_lev': (_('اللهجة الشامية'), 'the everyday Levantine Arabic of Syria, Lebanon and Jordan'),
    'en': (_('الإنجليزية'), 'natural, clear English'),
}

REPOST_AFTER = datetime.timedelta(days=60)  # a post may come back this long after it went out
COPIED = ('platforms', 'format', 'pillar', 'objective', 'template', 'scheme', 'motif', 'vectors', 'size', 'background',
          'title', 'headline', 'subheadline', 'cta', 'badge', 'caption', 'hashtags', 'visual_notes', 'video_script')


def variant_choices():
    return [(key, label) for key, (label, _rule) in VARIANTS.items()]


def make_copy(post, data, *, created_by=None, **fields):
    """A new post in the same company with `post`'s fields, the AI's texts (`data`) and `fields` on top."""
    from .services import _clip
    values = {name: getattr(post, name) for name in COPIED}
    values['plan'] = post.plan
    for name in ('title', 'headline', 'subheadline', 'cta', 'badge', 'caption', 'hashtags', 'visual_notes', 'video_script'):
        if name in data:
            values[name] = _clip(name, data[name])
    if post.format != Post.Format.REEL:
        values['video_script'] = ''
    values.update(fields)
    values['title'] = (values['title'] or post.title)[:200]
    return Post.objects.create(company=post.company, source_post=post, created_by=created_by or post.created_by,
                               status=Post.Status.REVIEW, scheduled_at=values.pop('scheduled_at', post.scheduled_at), **values)


def candidates(company, now=None, limit=6):
    """Older published posts worth bringing back: marked evergreen first, then the best performers.
    Posts reposted (or brought back) in the last REPOST_AFTER are left out."""
    now = now or timezone.now()
    recent_copies = Post.objects.filter(company=company, language='', source_post__isnull=False,
                                        created_at__gte=now - REPOST_AFTER).values_list('source_post_id', flat=True)
    qs = (Post.objects.filter(company=company, status=Post.Status.PUBLISHED, published_at__lte=now - REPOST_AFTER,
                              source_post__isnull=True)
          .exclude(pk__in=list(recent_copies))
          .exclude(format=Post.Format.REEL))
    scored = []
    for post in qs.prefetch_related('insights')[:200]:
        engagement = sum(i.engagement for i in post.insights.all())
        if post.evergreen or engagement:
            scored.append((post.evergreen, engagement, post))
    scored.sort(key=lambda s: (s[0], s[1]), reverse=True)
    return [(post, engagement) for _ev, engagement, post in scored[:limit]]


def free_slot(company, start, end, rng=None):
    """A time in [start, end) on a day with no post yet, at one of the brand's best hours (19:00 without data)."""
    from apps.insights.services import best_slots
    rng = rng or random.Random()
    hours = [h for h, _n, _avg in best_slots(company)] or [19]
    tz = company.tzinfo
    taken = {p.astimezone(tz).date() for p in Post.objects.filter(company=company, scheduled_at__gte=start, scheduled_at__lt=end)
             .values_list('scheduled_at', flat=True)}
    day = max(start, timezone.now()).astimezone(tz).date() + datetime.timedelta(days=1)
    days = []
    while datetime.datetime.combine(day, datetime.time.min, tzinfo=tz) < end:
        if day not in taken:
            days.append(day)
        day += datetime.timedelta(days=1)
    if not days:
        return None
    return datetime.datetime.combine(rng.choice(days), datetime.time(rng.choice(hours)), tzinfo=tz)


def run_variant(job):
    from apps.ai import planner
    post = Post.objects.select_related('company').get(pk=job.params['post_id'], company=job.company)
    label, rule = VARIANTS[job.params['language']]
    job.set_progress(20, _('وكيل يكتب النسخة…'))
    result = planner.adapt_post(post, f'Rewrite every text of this post (caption, hashtags and the design text) in {rule}. '
                                      'Keep the idea, the facts and the call to action; adapt expressions so they sound native, '
                                      'not translated. Hashtags in the new language where natural.')
    job.add_usage(result)
    copy = make_copy(post, result.data, language=job.params['language'], created_by=job.created_by,
                     title=f'{result.data.get("title") or post.title} · {label}')
    _render(job, copy)
    job.params['result_post_id'] = copy.pk
    job.save(update_fields=['params'])
    return _('أُنشئت نسخة %(label)s.') % {'label': label}


def run_repost(job):
    """Bring back an older post with new words and a new look. With `plan_id`, the repost lands in that plan's month."""
    from apps.ai import planner
    from apps.studio.art import direct

    from .models import ContentPlan
    post = Post.objects.select_related('company', 'plan').get(pk=job.params['post_id'], company=job.company)
    plan = ContentPlan.objects.filter(pk=job.params.get('plan_id'), company=job.company).first()
    rng = random.Random(job.pk)
    if plan:
        start = datetime.datetime.combine(plan.month, datetime.time.min, tzinfo=job.company.tzinfo)
        end = datetime.datetime.combine((plan.month + datetime.timedelta(days=32)).replace(day=1), datetime.time.min, tzinfo=job.company.tzinfo)
    else:
        start, end = timezone.now(), timezone.now() + datetime.timedelta(days=30)
    when = free_slot(job.company, start, end, rng)
    job.set_progress(20, _('وكيل يعيد صياغة المنشور…'))
    result = planner.adapt_post(post, 'This post did well and is being published again. Keep the idea and the facts, but write it '
                                      'fresh: a new hook, new headline and new caption wording, so followers do not feel it is a copy.')
    job.add_usage(result)
    look = direct([{'template': '', 'scheme': '', 'motif': '', 'format': post.format}], has_photos=bool(post.background_id), seed=job.pk)[0]
    copy = make_copy(post, result.data, plan=plan, scheduled_at=when, created_by=job.created_by,
                     scheme=look['scheme'], motif=look['motif'], variant=look['variant'])
    _render(job, copy)
    job.params['result_post_id'] = copy.pk
    job.save(update_fields=['params'])
    return _('جُهّز «%(title)s» لإعادة النشر.') % {'title': copy.title}


def _render(job, post):
    if post.format == Post.Format.REEL:
        return
    from apps.studio.render import render_posts
    job.set_progress(70, _('تصميم الصورة…'))
    render_posts([post])


def schedule_evergreen(plan, user=None):
    """After a plan is generated: queue the company's monthly evergreen reposts into it."""
    from apps.jobs.models import Job
    company = plan.company
    if not company.evergreen_per_month:
        return 0
    picked = candidates(company, limit=company.evergreen_per_month)
    for post, _engagement in picked:
        Job.enqueue(company, Job.Kind.REPOST, user, post_id=post.pk, plan_id=plan.pk)
    return len(picked)
