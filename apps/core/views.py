import datetime

from django.db.models import Count, Q
from django.shortcuts import redirect, render
from django.utils import timezone

from apps.companies.decorators import company_required
from apps.content.forms import ARABIC_MONTHS
from apps.content.models import ContentPlan, Post
from apps.jobs.models import Job


def home(request):
    if request.user.is_authenticated:
        return redirect('core:dashboard')
    return render(request, 'core/home.html')


@company_required
def dashboard(request):
    company = request.company
    now = timezone.localtime()
    month_start = now.replace(day=1, hour=0, minute=0, second=0, microsecond=0)
    next_month = (month_start + datetime.timedelta(days=32)).replace(day=1)
    plans = ContentPlan.objects.filter(company=company)
    current_plan = plans.filter(month=month_start.date()).first()
    if current_plan is None:
        # Plans are usually prepared ahead, so near a month's end the one worth showing is next month's.
        current_plan = plans.filter(month=next_month.date()).first()
        if current_plan is not None:
            month_start = next_month
            next_month = (month_start + datetime.timedelta(days=32)).replace(day=1)
    # Late in the month, nudge the team to prepare the next one before it starts.
    upcoming_month = (now.replace(day=1) + datetime.timedelta(days=32)).replace(day=1)
    plan_reminder = None
    if now.day >= 20 and not plans.filter(month=upcoming_month.date()).exists():
        plan_reminder = f'{ARABIC_MONTHS[upcoming_month.month - 1]} {upcoming_month.year}'
    month_posts = Post.objects.filter(company=company, scheduled_at__gte=month_start, scheduled_at__lt=next_month)
    counts = month_posts.aggregate(
        total=Count('pk'),
        review=Count('pk', filter=Q(status=Post.Status.REVIEW)),
        approved=Count('pk', filter=Q(status=Post.Status.APPROVED)),
        published=Count('pk', filter=Q(status=Post.Status.PUBLISHED)),
    )
    upcoming = (Post.objects.filter(company=company, scheduled_at__gte=now)
                .exclude(status=Post.Status.PUBLISHED).order_by('scheduled_at')[:6])
    overdue = Post.objects.filter(company=company, scheduled_at__lt=now,
                                  status__in=[Post.Status.APPROVED, Post.Status.REVIEW]).count()
    return render(request, 'core/dashboard.html', {
        'counts': counts,
        'upcoming': upcoming,
        'overdue': overdue,
        'current_plan': current_plan,
        'month_label': f'{ARABIC_MONTHS[month_start.month - 1]} {month_start.year}',
        'plans': plans[:4],
        'plan_reminder': plan_reminder,
        'running_jobs': Job.objects.filter(company=company, status__in=[Job.Status.PENDING, Job.Status.RUNNING]).count(),
        'now': now,
    })
