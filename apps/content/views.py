import datetime

from django.contrib import messages
from django.core.paginator import Paginator
from django.db.models import CharField, Q
from django.db.models.functions import Cast
from django.http import FileResponse, Http404, HttpResponse, JsonResponse
from django.shortcuts import get_object_or_404, redirect, render
from django.utils import timezone
from django.views.decorators.http import require_POST

from apps.companies.decorators import company_required
from apps.companies.models import MediaAsset
from apps.jobs.models import Job
from apps.jobs.runner import worker_alive
from apps.studio.designs import SIZES, TEMPLATES

from .forms import ARABIC_MONTHS, PlanForm, PostForm
from .models import ContentPlan, Platform, Post
from .occasions import between as in_range
from .review import share_url
from .services import default_size

WEEKDAYS = ['الأحد', 'الإثنين', 'الثلاثاء', 'الأربعاء', 'الخميس', 'الجمعة', 'السبت']


# --- Plans ------------------------------------------------------------------

@company_required
def plan_list(request):
    plans = ContentPlan.objects.filter(company=request.company).prefetch_related('posts')
    return render(request, 'content/plan_list.html', {'plans': plans})


@company_required(edit=True)
def plan_create(request):
    form = PlanForm(request.POST or None)
    if request.method == 'POST' and form.is_valid():
        plan = form.save(commit=False)
        plan.company, plan.created_by = request.company, request.user
        plan.save()
        job = Job.enqueue(request.company, Job.Kind.GENERATE_PLAN, request.user, plan_id=plan.pk)
        return redirect(f'{plan.get_absolute_url()}?job={job.pk}')
    return render(request, 'content/plan_form.html', {'form': form})


@company_required
def plan_detail(request, pk):
    plan = get_object_or_404(ContentPlan, pk=pk, company=request.company)
    job = None
    if plan.status == ContentPlan.Status.GENERATING:
        job = Job.objects.filter(company=request.company, kind=Job.Kind.GENERATE_PLAN,
                                 params__plan_id=plan.pk).order_by('-created_at').first()
    render_job = (Job.objects.filter(company=request.company, kind=Job.Kind.RENDER_PLAN, params__plan_id=plan.pk,
                                     status__in=[Job.Status.PENDING, Job.Status.RUNNING]).first())
    posts = plan.posts.select_related('background').order_by('scheduled_at')
    return render(request, 'content/plan_detail.html', {
        'review_ids': [p.pk for p in posts if p.status == Post.Status.REVIEW],
        'plan': plan, 'posts': posts, 'job': job, 'render_job': render_job, 'worker_alive': worker_alive(),
        'month_name': ARABIC_MONTHS[plan.month.month - 1],
        'month_label': f'{ARABIC_MONTHS[plan.month.month - 1]} {plan.month.year}',
        'share_url': share_url(plan),
    })


@company_required(edit=True)
@require_POST
def plan_regenerate(request, pk):
    plan = get_object_or_404(ContentPlan, pk=pk, company=request.company)
    plan.status, plan.error = ContentPlan.Status.GENERATING, ''
    plan.save(update_fields=['status', 'error'])
    job = Job.enqueue(request.company, Job.Kind.GENERATE_PLAN, request.user, plan_id=plan.pk)
    return redirect(f'{plan.get_absolute_url()}?job={job.pk}')


@company_required(manage=True)
@require_POST
def plan_delete(request, pk):
    plan = get_object_or_404(ContentPlan, pk=pk, company=request.company)
    plan.posts.all().delete()
    plan.delete()
    messages.success(request, 'تم حذف الخطة ومنشوراتها.')
    return redirect('content:plan_list')


# --- Calendar ---------------------------------------------------------------

@company_required
def calendar_view(request):
    today = timezone.localdate()
    try:
        month = datetime.date.fromisoformat(request.GET.get('month', '') + '-01')
    except ValueError:
        month = today.replace(day=1)
    prev_month = (month - datetime.timedelta(days=1)).replace(day=1)
    next_month = (month + datetime.timedelta(days=32)).replace(day=1)

    # Weeks start on Sunday; pad the grid to whole weeks.
    start = month - datetime.timedelta(days=(month.weekday() + 1) % 7)
    end = next_month + datetime.timedelta(days=(6 - (next_month.weekday() + 1) % 7) % 7)
    tz = request.company.tzinfo
    posts = Post.objects.filter(
        company=request.company,
        scheduled_at__gte=datetime.datetime.combine(start, datetime.time.min, tzinfo=tz),
        scheduled_at__lt=datetime.datetime.combine(end + datetime.timedelta(days=1), datetime.time.min, tzinfo=tz),
    ).order_by('scheduled_at')
    by_day = {}
    for post in posts:
        by_day.setdefault(timezone.localtime(post.scheduled_at).date(), []).append(post)

    weeks, day = [], start
    while day <= end:
        weeks.append([{'date': d, 'posts': by_day.get(d, []), 'in_month': d.month == month.month, 'today': d == today}
                      for d in (day + datetime.timedelta(days=i) for i in range(7))])
        day += datetime.timedelta(days=7)

    occasions = {}
    for o in in_range(request.company, start, end):
        occasions.setdefault(o['date'], []).append(o)
    for week in weeks:
        for cell in week:
            cell['occasions'] = occasions.get(cell['date'], [])

    unscheduled = Post.objects.filter(company=request.company, scheduled_at__isnull=True).count()
    return render(request, 'content/calendar.html', {
        'weeks': weeks, 'weekdays': WEEKDAYS, 'month': month,
        'month_label': f'{ARABIC_MONTHS[month.month - 1]} {month.year}',
        'prev_month': prev_month, 'next_month': next_month, 'unscheduled': unscheduled,
    })


# --- Posts ------------------------------------------------------------------

@company_required
def post_list(request):
    posts = Post.objects.filter(company=request.company).select_related('plan')
    status = request.GET.get('status', '')
    platform = request.GET.get('platform', '')
    q = request.GET.get('q', '').strip()
    if status in Post.Status.values:
        posts = posts.filter(status=status)
    if platform in Platform.values:
        # JSON "contains" isn't available on every backend; match the serialized list instead.
        posts = posts.annotate(platforms_text=Cast('platforms', CharField())).filter(platforms_text__icontains=f'"{platform}"')
    if q:
        posts = posts.filter(Q(title__icontains=q) | Q(caption__icontains=q))
    posts = posts.order_by('-scheduled_at', '-pk')
    page = Paginator(posts, 24).get_page(request.GET.get('page'))
    return render(request, 'content/post_list.html', {
        'page': page, 'status': status, 'platform': platform, 'q': q,
        'statuses': Post.Status.choices, 'platforms': Platform.choices,
    })


@company_required(edit=True)
@require_POST
def post_create(request):
    date = request.POST.get('date', '')
    try:
        day = datetime.date.fromisoformat(date)
    except ValueError:
        day = timezone.localdate() + datetime.timedelta(days=1)
    platforms = [Platform.FACEBOOK, Platform.INSTAGRAM]
    post = Post.objects.create(
        company=request.company, created_by=request.user, title='منشور جديد', platforms=platforms,
        status=Post.Status.DRAFT, size=default_size(Post.Format.IMAGE, platforms),
        scheduled_at=datetime.datetime.combine(day, datetime.time(19, 0), tzinfo=request.company.tzinfo),
        headline=request.company.name,
    )
    return redirect('content:post_edit', pk=post.pk)


@company_required
def post_edit(request, pk):
    post = get_object_or_404(Post.objects.select_related('background', 'plan'), pk=pk, company=request.company)
    if request.method == 'POST':
        if not request.membership.can_edit:
            return JsonResponse({'ok': False, 'error': 'صلاحيتك للمشاهدة فقط.'}, status=403)
        before = {f: getattr(post, f) for f in Post.DESIGN_FIELDS}
        form = PostForm(request.POST, instance=post, company=request.company)
        if not form.is_valid():
            return JsonResponse({'ok': False, 'errors': form.errors}, status=400)
        post = form.save(commit=False)
        design_changed = any(getattr(post, f) != v for f, v in before.items())
        if design_changed:
            post.image_stale = True
        post.save()
        job = None
        if (design_changed or not post.image) and not post.is_video:
            job = Job.enqueue(request.company, Job.Kind.RENDER_POST, request.user, post_id=post.pk)
        return JsonResponse({'ok': True, 'render_job': job.pk if job else None, 'saved_at': timezone.localtime().strftime('%H:%M')})

    form = PostForm(instance=post, company=request.company)
    return render(request, 'content/post_edit.html', {
        'post': post, 'form': form,
        'templates': TEMPLATES, 'sizes': SIZES,
        'assets': MediaAsset.objects.filter(company=request.company)[:60],
        'statuses': Post.Status,
        'comments': post.comments.select_related('user'),
        'plan_posts': list(post.plan.posts.order_by('scheduled_at').values_list('pk', flat=True)) if post.plan else [],
        'quick_rewrites': [
            'اجعل النص أقصر وأكثر تركيزاً',
            'اجعل الأسلوب أكثر حماساً وجاذبية',
            'اكتب عنواناً أقوى يلفت الانتباه',
            'أضف دعوة أوضح لاتخاذ إجراء',
            'اكتب فكرة مختلفة تماماً لنفس المحور',
        ],
    })


@company_required(edit=True)
@require_POST
def post_delete(request, pk):
    get_object_or_404(Post, pk=pk, company=request.company).delete()
    messages.success(request, 'تم حذف المنشور.')
    return redirect(request.POST.get('next') or 'content:post_list')


@company_required
def post_download(request, pk):
    post = get_object_or_404(Post, pk=pk, company=request.company)
    if not post.image:
        raise Http404
    return FileResponse(post.image.open('rb'), as_attachment=True, filename=f'wakeel-post-{post.pk}.png')


@company_required
def post_captions_export(request, pk):
    """All captions of a plan as a single text file, handy for manual publishing."""
    plan = get_object_or_404(ContentPlan, pk=pk, company=request.company)
    lines = []
    for post in plan.posts.order_by('scheduled_at'):
        when = timezone.localtime(post.scheduled_at).strftime('%Y-%m-%d %H:%M') if post.scheduled_at else '—'
        lines += [f'### {when} | {", ".join(post.platforms)} | {post.title}', post.full_caption]
        if post.video_script:
            lines += ['', '[سيناريو الفيديو]', post.video_script]
        lines.append('\n')
    response = HttpResponse('\n'.join(lines), content_type='text/plain; charset=utf-8')
    response['Content-Disposition'] = f'attachment; filename="wakeel-plan-{plan.month:%Y-%m}.txt"'
    return response
