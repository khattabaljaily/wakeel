"""The client review page: a secret link to one plan where the client approves
posts, asks for changes, or comments, without an account in Wakeel."""
import json
import secrets

from django.conf import settings
from django.contrib import messages
from django.http import Http404, JsonResponse
from django.shortcuts import get_object_or_404, redirect, render
from django.urls import reverse
from django.utils import timezone
from django.views.decorators.csrf import ensure_csrf_cookie
from django.views.decorators.http import require_POST

from apps.companies.decorators import company_required

from . import events
from .forms import ARABIC_MONTHS
from .models import ContentPlan, Post, PostComment
from .services import set_status


def share_url(plan):
    return settings.SITE_URL + reverse('review:plan', args=[plan.share_token]) if plan.share_token else ''


@company_required(manage=True)
@require_POST
def plan_share(request, pk):
    plan = get_object_or_404(ContentPlan, pk=pk, company=request.company)
    if request.POST.get('action') == 'off':
        plan.share_token = ''
        messages.success(request, 'تم إيقاف رابط العميل. لم يعد الرابط القديم يعمل.')
    else:  # on, or a fresh link that invalidates the old one
        plan.share_token = secrets.token_urlsafe(24)
        messages.success(request, 'رابط العميل جاهز. انسخه وأرسله للعميل.')
    plan.save(update_fields=['share_token'])
    return redirect(plan.get_absolute_url() + '#share')


def _plan(token):
    if not token:
        raise Http404
    plan = get_object_or_404(ContentPlan.objects.select_related('company'), share_token=token,
                             status=ContentPlan.Status.READY)
    if not plan.company.is_usable:  # the link stops working while the subscription is off
        raise Http404
    return plan


@ensure_csrf_cookie
def plan_review(request, token):
    plan = _plan(token)
    timezone.activate(plan.company.tzinfo)  # the client sees the brand's local times (the middleware resets it)
    posts = plan.posts.prefetch_related('comments__user').order_by('scheduled_at')
    return render(request, 'content/review.html', {
        'plan': plan, 'brand': plan.company, 'posts': posts,
        'month_label': f'{ARABIC_MONTHS[plan.month.month - 1]} {plan.month.year}',
        'pending': sum(p.status == Post.Status.REVIEW for p in posts),
    })


@require_POST
def post_feedback(request, token, pk):
    plan = _plan(token)
    post = get_object_or_404(Post, pk=pk, plan=plan)
    try:
        data = json.loads(request.body or b'{}')
    except json.JSONDecodeError:
        data = {}
    action, name = data.get('action'), (data.get('name') or '').strip()[:80]
    body = (data.get('body') or '').strip()[:2000]
    if not name:
        return JsonResponse({'error': 'اكتب اسمك أولاً ليعرف الفريق صاحب الملاحظة.'}, status=400)
    if action not in ('approve', 'changes', 'comment'):
        return JsonResponse({'error': 'طلب غير صالح.'}, status=400)
    if action in ('changes', 'comment') and not body:
        return JsonResponse({'error': 'اكتب ملاحظتك أولاً.'}, status=400)
    if action != 'comment' and post.status == Post.Status.PUBLISHED:
        return JsonResponse({'error': 'نُشر هذا المنشور بالفعل.'}, status=400)

    kind = {'approve': PostComment.Kind.APPROVAL, 'changes': PostComment.Kind.CHANGES}.get(action, PostComment.Kind.COMMENT)
    if action == 'approve':
        set_status(post, Post.Status.APPROVED)
    elif action == 'changes':
        set_status(post, Post.Status.DRAFT, note=f'{name} (العميل): {body}')
    comment = PostComment.objects.create(post=post, guest_name=name, kind=kind, body=body)
    events.comment_added(comment)
    return JsonResponse({'status': post.status, 'status_label': post.get_status_display()})
