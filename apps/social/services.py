"""Publish approved posts to the connected Meta accounts, now or at their scheduled time."""
import datetime
import io
import logging
import uuid

from django.conf import settings
from django.core.files.base import ContentFile
from django.core.files.storage import default_storage
from django.db import transaction
from django.db.models import Q
from django.utils import timezone
from django.utils.functional import lazy
from django.utils.text import format_lazy
from django.utils.translation import gettext_lazy as _
from PIL import Image

from apps.content.models import Post
from apps.content.services import set_status
from apps.notifications.services import managers, notify

from .meta import MetaError, publish_facebook, publish_instagram
from .models import SocialAccount

logger = logging.getLogger(__name__)

# Meta publishing covers still images and stories; reels need a video the team shoots.
PUBLISHABLE_FORMATS = (Post.Format.IMAGE, Post.Format.STORY)
# A post whose time passed longer ago than this (worker was down, say) is left for a human to decide.
LATE_LIMIT = datetime.timedelta(hours=6)


class PublishError(Exception):
    """Why a post can't be published (Arabic, shown to the user)."""


def targets(post, accounts=None):
    """The connected accounts this post should go to."""
    if accounts is None:
        accounts = SocialAccount.objects.filter(company=post.company)
    return [a for a in accounts if a.platform in post.platforms]


def check_publishable(post):
    if post.format not in PUBLISHABLE_FORMATS:
        raise PublishError(_('الفيديو القصير يُنشر يدوياً بعد تصويره؛ النشر التلقائي يدعم الصور والقصص فقط.'))
    if not targets(post):
        raise PublishError(_('لا يوجد حساب مربوط لمنصات هذا المنشور. اربط فيسبوك أو إنستغرام من «حسابات النشر».'))


def _jpeg_copy(post):
    """Instagram accepts JPEG only, fetched from a public URL: save a temporary JPEG under MEDIA."""
    with post.image.open('rb') as f, Image.open(f) as im:
        buf = io.BytesIO()
        im.convert('RGB').save(buf, 'JPEG', quality=92)
    name = default_storage.save(f'publish/{uuid.uuid4().hex}.jpg', ContentFile(buf.getvalue()))
    return name, settings.SITE_URL + default_storage.url(name)


def publish(post, actor=None):
    """Publish to every connected target not done yet. Marks the post published when all of them succeed."""
    check_publishable(post)
    if not post.image or post.image_stale:
        from apps.studio.render import render_posts
        render_posts([post])
        post.refresh_from_db()
    story = post.format == Post.Format.STORY
    done, errors = dict(post.external_ids or {}), []
    for account in targets(post):
        if account.platform in done:
            continue  # already published there on an earlier attempt
        try:
            if account.platform == SocialAccount.Platform.FACEBOOK:
                done['facebook'] = publish_facebook(account.external_id, account.access_token, post.full_caption,
                                                    post.image.path, story=story)
            else:
                name, url = _jpeg_copy(post)
                try:
                    done['instagram'] = publish_instagram(account.external_id, account.access_token, post.full_caption,
                                                          url, story=story)
                finally:
                    default_storage.delete(name)
        except MetaError as exc:
            errors.append(f'{account.get_platform_display()}: {exc}')
            if exc.expired:
                account.last_error = str(exc)
                account.save(update_fields=['last_error'])
        else:
            if account.last_error:
                account.last_error = ''
                account.save(update_fields=['last_error'])

    post.external_ids = done
    post.publish_error = '\n'.join(errors)
    post.save(update_fields=['external_ids', 'publish_error', 'updated_at'])
    if errors:
        notify(managers(post.company), post.company, format_lazy(_('تعذّر نشر «{title}»: {error}'), title=post.title, error=post.publish_error),
               post.get_absolute_url(), icon='bi-exclamation-triangle', email=True)
        raise PublishError(post.publish_error)
    set_status(post, Post.Status.PUBLISHED)
    notify(managers(post.company), post.company,
           format_lazy(_('نُشر «{title}» على {platforms}.'), title=post.title, platforms=_names_text(done)),
           post.get_absolute_url(), icon='bi-send-check', actor=actor)
    return done


def _names(done):
    labels = dict(SocialAccount.Platform.choices)
    return [labels.get(k, k) for k in done]


def _names_text(done):
    """The platform names joined as a phrase, evaluated lazily in the reader's language."""
    return lazy(lambda: str(_('، ')).join(str(n) for n in _names(done)), str)()


def due_posts(now=None):
    """Approved posts whose time has come, in companies that turned auto-publishing on."""
    now = now or timezone.now()
    return (Post.objects.select_related('company')
            .filter(status=Post.Status.APPROVED, company__auto_publish=True, publish_attempted_at__isnull=True,
                    company__is_approved=True, company__is_active=True,
                    scheduled_at__lte=now, scheduled_at__gte=now - LATE_LIMIT, format__in=PUBLISHABLE_FORMATS)
            .filter(company__social_accounts__isnull=False)
            .filter(Q(company__subscription_expires__isnull=True) | Q(company__subscription_expires__gte=timezone.localdate()))
            .distinct())


def enqueue_due(now=None):
    """Queue a publish job for each due post (called by the worker loop). Each post is tried once automatically."""
    from apps.jobs.models import Job
    queued = 0
    for post in due_posts(now):
        with transaction.atomic():
            # Claim the post so a second loop can't queue it twice.
            if not Post.objects.filter(pk=post.pk, publish_attempted_at__isnull=True).update(
                    publish_attempted_at=timezone.now()):
                continue
            Job.enqueue(post.company, Job.Kind.PUBLISH_POST, None, post_id=post.pk, automatic=True)
            queued += 1
    return queued


def run_publish_post(job):
    post = Post.objects.select_related('company').get(pk=job.params['post_id'], company=job.company)
    if post.status == Post.Status.PUBLISHED:
        return _('المنشور منشور بالفعل.')
    if job.params.get('automatic') and post.status != Post.Status.APPROVED:
        return _('تغيّرت حالة المنشور، فلم يُنشر تلقائياً.')
    job.set_progress(20, _('جارٍ النشر…'))
    done = publish(post, actor=job.created_by)
    return _('نُشر على %(platforms)s.') % {'platforms': _names_text(done)}
