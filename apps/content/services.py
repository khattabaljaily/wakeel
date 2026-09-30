"""Turn the AI's JSON into plans and posts, and run the jobs that produce it."""
import calendar
import datetime

from django.db import transaction
from django.utils import timezone

from apps.ai import planner
from apps.ai.client import AIError
from apps.studio.designs import TEMPLATES

from . import events
from .models import ContentPlan, Post

_TEXT_LIMITS = {f.name: f.max_length for f in Post._meta.get_fields() if getattr(f, 'max_length', None)}


def _clip(field, value):
    value = str(value or '').strip()
    limit = _TEXT_LIMITS.get(field)
    return value[:limit] if limit else value


def _list(value):
    return value if isinstance(value, list) else []


def _parse_time(value):
    try:
        hour, minute = (int(part) for part in str(value).split(':')[:2])
        return datetime.time(min(max(hour, 0), 23), min(max(minute, 0), 59))
    except (TypeError, ValueError):
        return datetime.time(19, 0)


def default_size(fmt, platforms):
    if fmt in (Post.Format.STORY, Post.Format.REEL):
        return Post.Size.STORY
    if 'instagram' in platforms:
        return Post.Size.PORTRAIT
    return Post.Size.SQUARE


def _post_fields(item, allowed_platforms):
    raw = item.get('platforms')
    raw = raw if isinstance(raw, list) else []
    platforms = [p for p in dict.fromkeys(map(str, raw)) if p in allowed_platforms] or list(allowed_platforms)
    fmt = item.get('format') if item.get('format') in Post.Format.values else Post.Format.IMAGE
    if 'tiktok' in platforms:
        fmt = Post.Format.REEL
    template = item.get('template') if item.get('template') in TEMPLATES else 'bold'
    fields = {
        name: _clip(name, item.get(name))
        for name in ('title', 'pillar', 'objective', 'caption', 'hashtags', 'headline', 'subheadline',
                     'cta', 'badge', 'visual_notes', 'video_script')
    }
    fields['title'] = fields['title'] or fields['headline'][:200] or 'منشور'
    fields.update(platforms=platforms, format=fmt, template=template, size=default_size(fmt, platforms))
    return fields


@transaction.atomic
def apply_plan(plan, data):
    """Store the strategy on the plan and replace its posts with the generated ones."""
    plan.title = _clip('title', data.get('title'))[:200]
    plan.summary = str(data.get('summary') or '').strip()
    plan.goals = [str(g) for g in _list(data.get('goals')) if g]
    plan.pillars = [p for p in _list(data.get('pillars')) if isinstance(p, dict)]
    plan.key_dates = [d for d in _list(data.get('key_dates')) if isinstance(d, dict)]
    plan.status = ContentPlan.Status.READY
    plan.error = ''
    plan.save()

    plan.posts.all().delete()
    tz = plan.company.tzinfo
    days = calendar.monthrange(plan.month.year, plan.month.month)[1]
    posts = []
    for item in data.get('posts') or []:
        if not isinstance(item, dict):
            continue
        try:
            day = min(max(int(item.get('day') or 1), 1), days)
        except (TypeError, ValueError):
            day = 1
        when = datetime.datetime.combine(plan.month.replace(day=day), _parse_time(item.get('time')), tzinfo=tz)
        posts.append(Post(
            company=plan.company, plan=plan, scheduled_at=when, status=Post.Status.REVIEW,
            created_by=plan.created_by, **_post_fields(item, plan.platforms),
        ))
    Post.objects.bulk_create(posts)
    return posts


def apply_rewrite(post, data):
    for name in ('title', 'headline', 'subheadline', 'cta', 'badge', 'caption', 'hashtags', 'visual_notes', 'video_script'):
        if name in data:
            setattr(post, name, _clip(name, data[name]))
    if not post.is_video:
        post.video_script = ''
    post.title = post.title or 'منشور'
    post.image_stale = True
    post.save()
    return post


def set_status(post, status, user=None, note=''):
    post.status = status
    if note:
        post.review_note = note
    elif status in (Post.Status.APPROVED, Post.Status.PUBLISHED):
        post.review_note = ''  # the requested changes were made
    if status == Post.Status.PUBLISHED and not post.published_at:
        post.published_at = timezone.now()
    elif status != Post.Status.PUBLISHED:
        post.published_at = None
    if status == Post.Status.APPROVED:
        post.publish_attempted_at = None  # (re)approved: auto-publishing may pick it up again
    post.save(update_fields=['status', 'review_note', 'published_at', 'publish_attempted_at', 'updated_at'])


# --- Job handlers (run by manage.py run_worker) -----------------------------

def run_generate_plan(job):
    plan = ContentPlan.objects.select_related('company').get(pk=job.params['plan_id'], company=job.company)
    job.set_progress(10, 'وكيل يدرس هوية الشركة ويضع الاستراتيجية…')
    try:
        result = planner.generate_plan(plan)
    except Exception as exc:
        if not job.was_cancelled():
            plan.status = ContentPlan.Status.FAILED
            plan.error = str(exc) if isinstance(exc, AIError) else 'حدث خطأ غير متوقع، وأُبلغ فريق الدعم. حاول مرة أخرى.'
            plan.save(update_fields=['status', 'error'])
            events.plan_failed(plan)
        raise
    job.add_usage(result)
    if job.was_cancelled():  # the user gave up while the AI was writing; drop the result
        return ''
    job.set_progress(80, 'حفظ المنشورات…')
    posts = apply_plan(plan, result.data)
    events.plan_ready(plan, len(posts))
    job.set_progress(90, f'تم إعداد {len(posts)} منشوراً. جارٍ تصميم الصور…')
    from apps.jobs.models import Job
    Job.enqueue(plan.company, Job.Kind.RENDER_PLAN, job.created_by, plan_id=plan.pk)
    return f'تم إعداد الخطة و{len(posts)} منشوراً.'


def run_rewrite_post(job):
    post = Post.objects.select_related('company').get(pk=job.params['post_id'], company=job.company)
    job.set_progress(20, 'وكيل يعيد كتابة المنشور…')
    result = planner.rewrite_post(post, job.params.get('instruction', ''))
    job.add_usage(result)
    apply_rewrite(post, result.data)
    if not post.is_video:
        from apps.studio.render import render_posts
        job.set_progress(80, 'تحديث التصميم…')
        render_posts([post])
    return 'تمت إعادة الكتابة.'


def run_render_post(job):
    from apps.studio.render import render_posts
    post = Post.objects.select_related('company', 'background').get(pk=job.params['post_id'], company=job.company)
    render_posts([post])
    return 'تم تحديث التصميم.'


def run_render_plan(job):
    from apps.studio.render import render_posts
    posts = list(
        Post.objects.select_related('company', 'background')
        .filter(plan_id=job.params['plan_id'], company=job.company)
        .exclude(format=Post.Format.REEL)
    )

    def progress(done, total):
        if job.was_cancelled():
            raise JobCancelled
        job.set_progress(int(done * 100 / max(total, 1)), f'تصميم الصور: {done} من {total}')

    try:
        render_posts(posts, progress=progress)
    except JobCancelled:
        return ''
    return f'تم تصميم {len(posts)} صورة.'


class JobCancelled(Exception):
    pass
