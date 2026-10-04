"""Client approvals over WhatsApp.

1. `invite(plan)` sends the client the approved review template (WhatsApp lets a business open a
   conversation only with a template) with a "start review" quick-reply button.
2. When the client taps it, each post awaiting review arrives as its design with the caption and two
   buttons: approve, or request changes.
3. "Request changes" asks for the note; the client's next text message becomes the change request.

Every button id carries a signature tied to the client's number, so ids can't be forged or replayed
from another number. Only the company's own client number is listened to.
"""
import hashlib
import hmac
import logging
import secrets

from django.conf import settings
from django.db import transaction
from django.utils import timezone, translation
from django.utils.translation import gettext as _

from apps.content import events, learning
from apps.content.models import ContentPlan, LearningSignal, Post, PostComment
from apps.content.services import set_status

from . import client
from .client import WhatsAppError, digits
from .models import ReviewSession

logger = logging.getLogger(__name__)


def _sig(kind, pk, phone):
    msg = f'{kind}:{pk}:{digits(phone)}'.encode()
    return hmac.new(settings.SECRET_KEY.encode(), msg, hashlib.sha256).hexdigest()[:12]


def button_id(kind, pk, phone):
    return f'{kind}:{pk}:{_sig(kind, pk, phone)}'


def parse_button(value, phone):
    """'ap:12:sig' -> ('ap', 12) when the signature matches this number, else None."""
    try:
        kind, pk, sig = str(value).split(':')
        pk = int(pk)
    except ValueError:
        return None
    return (kind, pk) if hmac.compare_digest(sig, _sig(kind, pk, phone)) else None


def _language(company):
    return 'en' if company.content_language == 'en' else 'ar'


def available(company):
    return settings.WHATSAPP_ENABLED and bool(digits(company.client_whatsapp))


def invite(plan):
    """Send the client the review invitation for this plan. Raises WhatsAppError."""
    from apps.content.forms import ARABIC_MONTHS
    from apps.content.review import share_url

    company = plan.company
    phone = digits(company.client_whatsapp)
    if not phone:
        raise WhatsAppError(_('أضف رقم واتساب العميل أولاً من إعدادات المخطط الآلي.'))
    if not plan.share_token:
        plan.share_token = secrets.token_urlsafe(24)
        plan.save(update_fields=['share_token'])
    month = f'{ARABIC_MONTHS[plan.month.month - 1]} {plan.month.year}'
    client.send_template(phone, [company.name, month, share_url(plan)], button_id('start', plan.pk, phone))
    ReviewSession.objects.update_or_create(plan=plan, phone=phone, defaults={'company': company, 'awaiting': None})


def _post_message(post):
    when = timezone.localtime(post.scheduled_at, post.company.tzinfo).strftime('%Y-%m-%d %H:%M') if post.scheduled_at else ''
    text = post.video_script if post.is_video else post.full_caption
    return f'*{post.title}*\n{when}\n\n{text}'[:1000]


def send_posts(session):
    """Every post of the plan still awaiting review, as image + approve / change buttons."""
    company, phone = session.company, session.phone
    posts = list(session.plan.posts.filter(status=Post.Status.REVIEW).order_by('scheduled_at'))
    if not posts:
        client.send_text(phone, _('لا توجد منشورات بانتظار المراجعة في هذه الخطة. شكراً لك!'))
        return 0
    client.send_text(phone, _('سأرسل لك %(count)s منشوراً، واحداً تلو الآخر. اعتمد ما يعجبك أو اطلب التعديل.') % {'count': len(posts)})
    for post in posts:
        buttons = [(button_id('ap', post.pk, phone), _('اعتماد ✅')), (button_id('ch', post.pk, phone), _('طلب تعديل ✏️'))]
        if post.image and not post.is_video:
            client.send_image_buttons(phone, settings.SITE_URL + post.image.url, _post_message(post), buttons)
        else:
            client.send_buttons(phone, _post_message(post), buttons)
    return len(posts)


def _guest(phone):
    return _('العميل (واتساب +%(phone)s)') % {'phone': phone}


def _session_for(phone, post=None, plan_id=None):
    qs = ReviewSession.objects.select_related('company', 'plan', 'awaiting').filter(phone=phone)
    if post is not None:
        qs = qs.filter(plan_id=post.plan_id)
    elif plan_id is not None:
        qs = qs.filter(plan_id=plan_id)
    return qs.order_by('-updated_at').first()


def handle_message(message):
    """One incoming WhatsApp message (from the webhook)."""
    phone = digits(message.get('from'))
    kind = message.get('type')
    reply = None
    if kind == 'button':
        reply = (message.get('button') or {}).get('payload')
    elif kind == 'interactive':
        reply = ((message.get('interactive') or {}).get('button_reply') or {}).get('id')
    if reply:
        parsed = parse_button(reply, phone)
        if parsed:
            _on_button(phone, *parsed)
        return
    if kind == 'text':
        _on_text(phone, ((message.get('text') or {}).get('body') or '').strip())


def _on_button(phone, kind, pk):
    if kind == 'start':
        session = _session_for(phone, plan_id=pk)
        if session and session.plan.company.is_usable:
            with translation.override(_language(session.company)):
                send_posts(session)
        return
    post = Post.objects.select_related('company', 'plan').filter(pk=pk).first()
    session = post and _session_for(phone, post=post)
    if not session or not post.company.is_usable:
        return
    with translation.override(_language(post.company)):
        if post.status == Post.Status.PUBLISHED:
            client.send_text(phone, _('نُشر هذا المنشور بالفعل.'))
        elif kind == 'ap':
            with transaction.atomic():
                set_status(post, Post.Status.APPROVED)
                comment = PostComment.objects.create(post=post, guest_name=_guest(phone), kind=PostComment.Kind.APPROVAL)
            events.comment_added(comment)
            session.awaiting = None
            session.save(update_fields=['awaiting', 'updated_at'])
            client.send_text(phone, _('تم اعتماد «%(title)s» ✅') % {'title': post.title})
        elif kind == 'ch':
            session.awaiting = post
            session.save(update_fields=['awaiting', 'updated_at'])
            client.send_text(phone, _('اكتب ملاحظتك على «%(title)s» في رسالة واحدة، وستصل إلى الفريق.') % {'title': post.title})


def _on_text(phone, body):
    session = (ReviewSession.objects.select_related('company', 'plan', 'awaiting')
               .filter(phone=phone, awaiting__isnull=False).order_by('-updated_at').first())
    if session is None:
        session = _session_for(phone)
        if session:
            from apps.content.review import share_url
            with translation.override(_language(session.company)):
                client.send_text(phone, _('لمراجعة الخطة كاملة افتح الرابط: %(link)s') % {'link': share_url(session.plan)})
        return
    post = session.awaiting
    if not body or not session.company.is_usable:
        return
    body = body[:2000]
    name = _guest(phone)
    with transaction.atomic():
        set_status(post, Post.Status.DRAFT, note=f'{name}: {body}')
        comment = PostComment.objects.create(post=post, guest_name=name, kind=PostComment.Kind.CHANGES, body=body)
        session.awaiting = None
        session.save(update_fields=['awaiting', 'updated_at'])
    learning.record_note(post, LearningSignal.Kind.CHANGES, body, from_client=True)
    events.comment_added(comment)
    with translation.override(_language(session.company)):
        client.send_text(phone, _('وصلت ملاحظتك على «%(title)s» إلى الفريق. شكراً!') % {'title': post.title})


def handle_payload(payload):
    """The webhook body: may batch several messages (and status updates, which are ignored)."""
    for entry in payload.get('entry') or []:
        for change in entry.get('changes') or []:
            value = change.get('value') or {}
            if str((value.get('metadata') or {}).get('phone_number_id', '')) not in ('', str(settings.WHATSAPP_PHONE_NUMBER_ID)):
                continue
            for message in value.get('messages') or []:
                try:
                    handle_message(message)
                except WhatsAppError:
                    logger.exception('WhatsApp reply failed')
