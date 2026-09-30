"""Wakeel learns each brand's taste from feedback.

Signals are recorded as the team and the client work (edits to AI-written text, change requests,
rewrite instructions, client comments). Before the next plan, or once enough pile up, they are
distilled by the AI into Company.lessons: short rules the planner and the rewriter follow. The team
can see, delete and add lessons on the brand page; manual lessons are never changed by the AI.
"""
import difflib

from django.db import transaction
from django.utils import timezone

from .models import LearningSignal, Post

# Text fields whose edits teach something about the brand's voice.
LEARNED_FIELDS = ('title', 'headline', 'subheadline', 'cta', 'caption', 'hashtags')
AUTO_LEARN_AFTER = 8  # distill in the background once this many new signals pile up
MANUAL_MAX = 20


def _changed(before, after):
    before, after = (before or '').strip(), (after or '').strip()
    if before == after or not before:
        return False
    return difflib.SequenceMatcher(None, before, after).ratio() < 0.97  # ignore a fixed comma


def record_edits(post, before):
    """After the team saves an AI-written post: one signal per changed text field.
    Repeated saves of the same field update the pending signal instead of adding new ones."""
    if not post.plan_id:
        return
    for field in LEARNED_FIELDS:
        old, new = before.get(field, ''), getattr(post, field)
        pending = LearningSignal.objects.filter(company=post.company, post=post, kind=LearningSignal.Kind.EDIT,
                                                field=field, used=False).first()
        if pending:
            if _changed(pending.before, new):
                pending.after = new
                pending.save(update_fields=['after'])
            else:  # edited back to what the AI wrote
                pending.delete()
        elif _changed(old, new):
            LearningSignal.objects.create(company=post.company, post=post, kind=LearningSignal.Kind.EDIT,
                                          field=field, before=old, after=new)
    _maybe_schedule(post.company)


def record_note(post, kind, note, *, from_client=False):
    note = (note or '').strip()
    if not note:
        return
    LearningSignal.objects.create(company=post.company, post=post, kind=kind, note=note[:2000], from_client=from_client)
    _maybe_schedule(post.company)


def pending(company):
    return LearningSignal.objects.filter(company=company, used=False)


def _maybe_schedule(company, user=None):
    from apps.jobs.models import Job
    if pending(company).count() < AUTO_LEARN_AFTER:
        return
    if not Job.objects.filter(company=company, kind=Job.Kind.LEARN, status__in=[Job.Status.PENDING, Job.Status.RUNNING]).exists():
        Job.enqueue(company, Job.Kind.LEARN, user)


def manual_lessons(company):
    return [l['text'] for l in company.lessons if l.get('manual')]


def all_lessons(company):
    """Manual lessons first (the team said them outright), then the learned ones."""
    manual = [l['text'] for l in company.lessons if l.get('manual')]
    learned = [l['text'] for l in company.lessons if not l.get('manual')]
    return manual + learned


def learn(company):
    """Distill pending signals into the company's learned lessons. Returns (AIResult or None, signals used)."""
    from apps.ai.learning import MAX_LESSONS, distill

    signals = list(pending(company).order_by('created_at')[:60])
    if not signals:
        return None, 0
    learned = [l['text'] for l in company.lessons if not l.get('manual')]
    result = distill(learned, signals)
    new = [str(t).strip() for t in result.data.get('lessons') or [] if str(t).strip()][:MAX_LESSONS]
    with transaction.atomic():
        company.lessons = [l for l in company.lessons if l.get('manual')] + [{'text': t[:300], 'manual': False} for t in new]
        company.lessons_updated_at = timezone.now()
        company.save(update_fields=['lessons', 'lessons_updated_at'])
        LearningSignal.objects.filter(pk__in=[s.pk for s in signals]).update(used=True)
    return result, len(signals)


def recent_posts(company, before_month, months=3):
    """Ideas already published or planned in the months before this plan, so the next one doesn't repeat them."""
    import datetime
    start = (before_month - datetime.timedelta(days=31 * months)).replace(day=1)
    # Aware datetime bounds, not __date: MySQL without timezone tables can't convert for __date lookups.
    tz = company.tzinfo
    bounds = [datetime.datetime.combine(d, datetime.time.min, tzinfo=tz) for d in (start, before_month)]
    return list(Post.objects.filter(company=company, scheduled_at__gte=bounds[0], scheduled_at__lt=bounds[1])
                .order_by('scheduled_at').values_list('scheduled_at', 'pillar', 'title')[:90])
