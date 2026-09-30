import datetime

from django.shortcuts import get_object_or_404
from django.utils import timezone
from rest_framework import status
from rest_framework.decorators import api_view, permission_classes
from rest_framework.permissions import IsAuthenticated
from rest_framework.response import Response

from apps.content.models import ContentPlan, Post
from apps.content.services import set_status
from apps.jobs.models import Job
from apps.jobs.runner import worker_alive

from .permissions import InCompany

PERMS = [IsAuthenticated, InCompany]
# Editors may move a post between draft and review; approving and marking as
# published is for owners/admins.
MANAGER_STATUSES = (Post.Status.APPROVED, Post.Status.PUBLISHED)


def _company(request):
    return request._request.company


def _can_set(request, new_status):
    return new_status not in MANAGER_STATUSES or request._request.membership.can_manage


@api_view(['GET'])
@permission_classes(PERMS)
def job_detail(request, pk):
    job = get_object_or_404(Job, pk=pk, company=_company(request))
    return Response({
        'id': job.pk, 'kind': job.kind, 'status': job.status, 'progress': job.progress,
        'message': job.message, 'error': job.error, 'finished': job.is_finished,
        'worker_alive': worker_alive(),
    })


@api_view(['POST'])
@permission_classes(PERMS)
def job_cancel(request, pk):
    """Stop waiting for a job. A job already running finishes its current step, but its result is discarded."""
    job = get_object_or_404(Job, pk=pk, company=_company(request))
    if not job.is_finished:
        job.status, job.finished_at, job.error = Job.Status.CANCELLED, timezone.now(), 'ألغاه المستخدم.'
        job.save(update_fields=['status', 'finished_at', 'error'])
        if job.kind == Job.Kind.GENERATE_PLAN:
            ContentPlan.objects.filter(pk=job.params.get('plan_id'), company=job.company,
                                       status=ContentPlan.Status.GENERATING).update(
                status=ContentPlan.Status.FAILED, error='أُلغي إعداد الخطة. يمكنك المحاولة مرة أخرى أو حذف الخطة.')
    return Response({'status': job.status})


@api_view(['POST'])
@permission_classes(PERMS)
def post_status(request, pk):
    post = get_object_or_404(Post, pk=pk, company=_company(request))
    new_status = request.data.get('status')
    if new_status not in Post.Status.values:
        return Response({'error': 'حالة غير معروفة.'}, status=status.HTTP_400_BAD_REQUEST)
    if not _can_set(request, new_status):
        return Response({'error': 'اعتماد المنشورات ونشرها متاح للمالك والمديرين فقط.'}, status=status.HTTP_403_FORBIDDEN)
    set_status(post, new_status, request.user, note=request.data.get('note', '').strip())
    return Response({'status': post.status, 'label': post.get_status_display()})


@api_view(['POST'])
@permission_classes(PERMS)
def posts_bulk_status(request):
    new_status = request.data.get('status')
    ids = [int(i) for i in request.data.get('ids', []) if str(i).isdigit()]
    if new_status not in Post.Status.values or not ids:
        return Response({'error': 'طلب غير صالح.'}, status=status.HTTP_400_BAD_REQUEST)
    if not _can_set(request, new_status):
        return Response({'error': 'اعتماد المنشورات ونشرها متاح للمالك والمديرين فقط.'}, status=status.HTTP_403_FORBIDDEN)
    posts = Post.objects.filter(company=_company(request), pk__in=ids)
    for post in posts:
        set_status(post, new_status, request.user)
    return Response({'updated': len(posts)})


@api_view(['POST'])
@permission_classes(PERMS)
def posts_bulk_delete(request):
    ids = [int(i) for i in request.data.get('ids', []) if str(i).isdigit()]
    deleted = 0
    for post in Post.objects.filter(company=_company(request), pk__in=ids):
        post.delete()  # one by one so each image file is removed too
        deleted += 1
    return Response({'deleted': deleted})


@api_view(['POST'])
@permission_classes(PERMS)
def post_reschedule(request, pk):
    """Move a post to another day (calendar drag and drop), keeping its time of day."""
    post = get_object_or_404(Post, pk=pk, company=_company(request))
    try:
        day = datetime.date.fromisoformat(request.data.get('date', ''))
    except (TypeError, ValueError):
        return Response({'error': 'تاريخ غير صالح.'}, status=status.HTTP_400_BAD_REQUEST)
    current = timezone.localtime(post.scheduled_at).time() if post.scheduled_at else datetime.time(19, 0)
    post.scheduled_at = datetime.datetime.combine(day, current, tzinfo=_company(request).tzinfo)
    post.save(update_fields=['scheduled_at', 'updated_at'])
    return Response({'scheduled_at': post.scheduled_at.isoformat()})


@api_view(['POST'])
@permission_classes(PERMS)
def post_rewrite(request, pk):
    post = get_object_or_404(Post, pk=pk, company=_company(request))
    instruction = (request.data.get('instruction') or '').strip()
    if not instruction:
        return Response({'error': 'اكتب ما تريد تغييره في المنشور.'}, status=status.HTTP_400_BAD_REQUEST)
    job = Job.enqueue(_company(request), Job.Kind.REWRITE_POST, request.user, post_id=post.pk, instruction=instruction[:1000])
    return Response({'job': job.pk}, status=status.HTTP_202_ACCEPTED)


@api_view(['POST'])
@permission_classes(PERMS)
def post_render(request, pk):
    post = get_object_or_404(Post, pk=pk, company=_company(request))
    job = Job.enqueue(_company(request), Job.Kind.RENDER_POST, request.user, post_id=post.pk)
    return Response({'job': job.pk}, status=status.HTTP_202_ACCEPTED)


@api_view(['GET'])
@permission_classes(PERMS)
def post_detail(request, pk):
    post = get_object_or_404(Post, pk=pk, company=_company(request))
    return Response({
        'id': post.pk, 'status': post.status, 'status_label': post.get_status_display(),
        'image': post.image.url if post.image else '', 'image_stale': post.image_stale,
        'updated': post.updated_at.timestamp(),
        **{f: getattr(post, f) for f in ('title', 'headline', 'subheadline', 'cta', 'badge', 'caption',
                                         'hashtags', 'visual_notes', 'video_script')},
    })


@api_view(['POST'])
@permission_classes(PERMS)
def plan_render(request, pk):
    plan = get_object_or_404(ContentPlan, pk=pk, company=_company(request))
    job = Job.enqueue(_company(request), Job.Kind.RENDER_PLAN, request.user, plan_id=plan.pk)
    return Response({'job': job.pk}, status=status.HTTP_202_ACCEPTED)
