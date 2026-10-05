"""The inbox: collect comments from Facebook and Instagram, let the AI read them, alert on crises, and reply."""
import datetime
import logging

from django.conf import settings

from django.utils import timezone
from django.utils.dateparse import parse_datetime
from django.utils.text import format_lazy
from django.utils.translation import gettext_lazy as _

from apps.content.models import Post
from apps.social import meta
from apps.social.meta import MetaError
from apps.social.models import SocialAccount

from .models import InboxItem

logger = logging.getLogger(__name__)

WINDOW_DAYS = 30  # comments are read on posts published this recently
BATCH = 30
CHECK_EVERY = datetime.timedelta(minutes=30)
AUTO_CATEGORIES = (InboxItem.Category.QUESTION, InboxItem.Category.PRAISE)


def _accounts(company):
    return {a.platform: a for a in SocialAccount.objects.filter(company=company)
            if a.platform in (SocialAccount.Platform.FACEBOOK, SocialAccount.Platform.INSTAGRAM)}


def fetch(company, now=None):
    """Store new comments. Returns (new items, problems)."""
    now = now or timezone.now()
    accounts = _accounts(company)
    if not accounts:
        return [], []
    posts = Post.objects.filter(company=company, status=Post.Status.PUBLISHED, published_at__gte=now - datetime.timedelta(days=WINDOW_DAYS))
    new, problems, dead = [], [], set()
    for post in posts:
        for platform, external in (post.external_ids or {}).items():
            account = accounts.get(platform)
            if account is None or platform in dead:
                continue
            try:
                if platform == SocialAccount.Platform.FACEBOOK:
                    comments = meta.facebook_comments(external, account.access_token)
                else:
                    comments = meta.instagram_comments(external, account.access_token)
            except MetaError as exc:
                problems.append(f'{account.get_platform_display()}: {exc}')
                if exc.expired:
                    dead.add(platform)
                continue
            for c in comments:
                if c['author_id'] in (account.external_id, account.name):  # the brand's own replies
                    continue
                item, created = InboxItem.objects.get_or_create(
                    company=company, platform=platform, external_id=c['id'],
                    defaults={'post': post, 'author': c['author'][:150], 'text': c['text'],
                              'received_at': parse_datetime(c['time'] or '') or now})
                if created:
                    new.append(item)
    return new, list(dict.fromkeys(problems))


def triage(company, job=None):
    """Let the AI read the comments not read yet; alert managers on the alarming ones; auto-reply when allowed."""
    from apps.ai.inbox import triage as ai_triage
    from apps.notifications.services import managers, notify

    pending = list(InboxItem.objects.filter(company=company, triaged=False).select_related('post')[:BATCH])
    if not pending:
        return 0
    result = ai_triage(company, pending)
    if job:
        job.add_usage(result)
    by_id = {i.pk: i for i in pending}
    for row in result.data.get('items') or []:
        item = by_id.get(row.get('id')) if isinstance(row, dict) else None
        if item is None:
            continue
        item.sentiment = row.get('sentiment') if row.get('sentiment') in InboxItem.Sentiment.values else InboxItem.Sentiment.NEUTRAL
        item.category = row.get('category') if row.get('category') in InboxItem.Category.values else InboxItem.Category.OTHER
        item.urgency = row.get('urgency') if row.get('urgency') in InboxItem.Urgency.values else InboxItem.Urgency.NORMAL
        item.suggested_reply = str(row.get('reply') or '').strip()[:2000]
        item.triaged = True
        item.save(update_fields=['sentiment', 'category', 'urgency', 'suggested_reply', 'triaged'])
        if item.is_alarming:
            label = _('أزمة محتملة') if item.urgency == InboxItem.Urgency.CRISIS else _('تعليق عاجل')
            notify(managers(company), company, format_lazy(_('{label} على «{post}»: {text}'), label=label,
                                                           post=item.post.title if item.post else '', text=item.text[:140]),
                   '/app/inbox/?view=urgent', icon='bi-exclamation-octagon', email=True)
        elif (company.inbox_auto_reply and item.category in AUTO_CATEGORIES and item.suggested_reply
              and item.sentiment != InboxItem.Sentiment.NEGATIVE):
            try:
                reply(item, item.suggested_reply, auto=True)
            except MetaError:
                logger.info('Auto-reply to %s failed', item.pk)
    # Items the AI skipped are tried again next time; don't loop on them forever.
    InboxItem.objects.filter(pk__in=[i.pk for i in pending], triaged=False, created_at__lt=timezone.now() - datetime.timedelta(days=1)) \
        .update(triaged=True, urgency=InboxItem.Urgency.NORMAL)
    return len(pending)


def reply(item, text, user=None, auto=False):
    """Answer the comment on its platform. Raises MetaError (the item keeps the error)."""
    text = (text or '').strip()[:2000]
    account = _accounts(item.company).get(item.platform)
    if account is None:
        raise MetaError(_('الحساب غير مربوط. اربطه من «حسابات النشر».'))
    try:
        if item.platform == SocialAccount.Platform.FACEBOOK:
            meta.reply_facebook(item.external_id, account.access_token, text)
        else:
            meta.reply_instagram(item.external_id, account.access_token, text)
    except MetaError as exc:
        item.reply_error = str(exc)[:300]
        item.save(update_fields=['reply_error'])
        raise
    item.status, item.reply_text, item.reply_error = InboxItem.Status.REPLIED, text, ''
    item.replied_at, item.replied_by, item.auto_replied = timezone.now(), user, auto
    item.save(update_fields=['status', 'reply_text', 'reply_error', 'replied_at', 'replied_by', 'auto_replied'])


def run_fetch_inbox(job):
    new, problems = fetch(job.company)
    job.set_progress(50, _('وكيل يقرأ التعليقات…'))
    read = triage(job.company, job)
    if problems and not new:
        job.error_detail = '\n'.join(problems)
    return _('تعليقات جديدة: %(new)s، قُرئ منها %(read)s.') % {'new': len(new), 'read': read}


def run_due(now=None):
    """Worker schedule: check each connected company's comments every CHECK_EVERY."""
    from apps.companies.models import Company
    from apps.jobs.models import Job
    now = now or timezone.now()
    queued = 0
    if not settings.META_INBOX_SCOPES:  # without the comment permissions Meta refuses every read
        return 0
    for company in Company.objects.filter(is_approved=True, is_active=True, social_accounts__isnull=False).distinct():
        if not company.is_usable:
            continue
        if not company.posts.filter(status=Post.Status.PUBLISHED, published_at__gte=now - datetime.timedelta(days=WINDOW_DAYS)).exists():
            continue
        if Job.objects.filter(company=company, kind=Job.Kind.FETCH_INBOX, created_at__gte=now - CHECK_EVERY).exists():
            continue
        Job.enqueue(company, Job.Kind.FETCH_INBOX)
        queued += 1
    return queued
