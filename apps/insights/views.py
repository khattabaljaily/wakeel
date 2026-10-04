import datetime

from django import forms
from django.core.exceptions import PermissionDenied
from django.contrib import messages
from django.http import Http404, JsonResponse
from django.shortcuts import get_object_or_404, redirect, render
from django.urls import reverse
from django.utils import timezone
from django.utils.translation import gettext_lazy as _
from django.views.decorators.http import require_POST

from apps.companies.decorators import company_required
from apps.jobs.models import Job
from apps.social.models import SocialAccount

from apps.content.copies import candidates
from apps.content.models import Post

from . import competitors, services, tasks
from .models import Competitor, CompetitorAnalysis, MonthlyReport, PostInsight

RANGES = {'30': 30, '90': 90, 'all': None}


def _month_choices(company):
    """The last six finished months, newest first."""
    month = tasks.previous_month(timezone.localdate())
    out = []
    for _i in range(6):
        out.append(month)
        month = tasks.previous_month(month)
    return out


@company_required
def dashboard(request):
    company = request.company
    key = request.GET.get('range') if request.GET.get('range') in RANGES else '30'
    days = RANGES[key]
    now = timezone.now()
    start = now - datetime.timedelta(days=days) if days else None
    data = services.summarize(company, start, None)
    accounts = SocialAccount.objects.filter(company=company).exclude(platform=SocialAccount.Platform.TIKTOK)
    published = company.posts.filter(status='published').count()
    weekdays = [_('الإثنين'), _('الثلاثاء'), _('الأربعاء'), _('الخميس'), _('الجمعة'), _('السبت'), _('الأحد')]
    for g in data['by_weekday']:
        g['label'] = weekdays[g['name']]
    peak = max((g['avg_engagement'] for g in data['by_weekday']), default=0) or 1
    peak_hour = max((g['avg_engagement'] for g in data['by_hour']), default=0) or 1
    return render(request, 'insights/dashboard.html', {
        'data': data, 'range': key, 'ranges': [('30', _('آخر 30 يوماً')), ('90', _('آخر 90 يوماً')), ('all', _('الكل'))],
        'accounts': accounts, 'published': published, 'slots': services.best_slots(company),
        'peak': peak, 'peak_hour': peak_hour,
        'last_fetch': PostInsight.objects.filter(post__company=company).order_by('-fetched_at').values_list('fetched_at', flat=True).first(),
        'reports': MonthlyReport.objects.filter(company=company)[:6],
        'evergreen': candidates(company),
        'months': _month_choices(company),
    })


@company_required(edit=True)
@require_POST
def refresh(request):
    if not Job.objects.filter(company=request.company, kind=Job.Kind.FETCH_INSIGHTS,
                              status__in=[Job.Status.PENDING, Job.Status.RUNNING]).exists():
        Job.enqueue(request.company, Job.Kind.FETCH_INSIGHTS, request.user)
    messages.success(request, _('جارٍ تحديث الأرقام من فيسبوك وإنستغرام. أعد تحميل الصفحة بعد لحظات.'))
    return redirect('insights:dashboard')


@company_required(edit=True)
@require_POST
def repost(request, pk):
    post = get_object_or_404(Post, pk=pk, company=request.company, status=Post.Status.PUBLISHED)
    Job.enqueue(request.company, Job.Kind.REPOST, request.user, post_id=post.pk)
    messages.success(request, _('يعيد وكيل صياغة «%(title)s» وتصميمه، وستجده في المنشورات بانتظار المراجعة خلال لحظات.') % {'title': post.title})
    return redirect('insights:dashboard')


@company_required
def report_list(request):
    return render(request, 'insights/report_list.html', {
        'reports': MonthlyReport.objects.filter(company=request.company),
        'months': _month_choices(request.company),
    })


@company_required(edit=True)
@require_POST
def report_create(request):
    try:
        month = datetime.date.fromisoformat(request.POST.get('month', ''))
    except ValueError:
        raise Http404
    month = month.replace(day=1)
    rep, created = MonthlyReport.objects.get_or_create(company=request.company, month=month)
    if created or rep.status == MonthlyReport.Status.FAILED or request.POST.get('again'):
        import secrets
        rep.status, rep.error = MonthlyReport.Status.GENERATING, ''
        rep.share_token = rep.share_token or secrets.token_urlsafe(24)
        rep.save()
        Job.enqueue(request.company, Job.Kind.GENERATE_REPORT, request.user, report_id=rep.pk)
    return redirect('insights:report', pk=rep.pk)


def _report_context(rep):
    stats = rep.stats or {}
    return {'report': rep, 'brand': rep.company, 'stats': stats, 'totals': stats.get('totals') or {},
            'month_label': tasks.month_label(rep.month)}


@company_required
def report_detail(request, pk):
    rep = get_object_or_404(MonthlyReport.objects.select_related('company'), pk=pk, company=request.company)
    return render(request, 'insights/report.html', {**_report_context(rep), 'share_link': tasks.share_url(rep)})


@company_required(manage=True)
@require_POST
def report_share(request, pk):
    import secrets
    rep = get_object_or_404(MonthlyReport, pk=pk, company=request.company)
    rep.share_token = '' if request.POST.get('action') == 'off' else secrets.token_urlsafe(24)
    rep.save(update_fields=['share_token'])
    messages.success(request, _('تم تحديث رابط التقرير.'))
    return redirect('insights:report', pk=rep.pk)


def public_report(request, token):
    if not token:
        raise Http404
    rep = get_object_or_404(MonthlyReport.objects.select_related('company'), share_token=token, status=MonthlyReport.Status.READY)
    if not rep.company.is_usable:
        raise Http404
    return render(request, 'insights/public_report.html', {**_report_context(rep), 'agency': rep.company.agency})


# --- Competitors ------------------------------------------------------------

class CompetitorForm(forms.ModelForm):
    class Meta:
        model = Competitor
        fields = ['name', 'website', 'social', 'sample_posts']
        widgets = {'sample_posts': forms.Textarea(attrs={'rows': 4}), 'website': forms.TextInput(attrs={'dir': 'ltr', 'placeholder': 'example.com'}),
                   'social': forms.TextInput(attrs={'dir': 'ltr'})}


@company_required
def competitor_list(request):
    company = request.company
    editing = None
    if request.GET.get('edit', '').isdigit():
        editing = get_object_or_404(Competitor, pk=request.GET['edit'], company=company)
    form = CompetitorForm(request.POST or None, instance=editing)
    if request.method == 'POST':
        if not request.membership.can_edit:
            raise PermissionDenied
        if not editing and Competitor.objects.filter(company=company).count() >= competitors.MAX_COMPETITORS:
            messages.error(request, _('يمكن إضافة %(n)s منافسين كحد أقصى.') % {'n': competitors.MAX_COMPETITORS})
            return redirect('competitors:list')
        if form.is_valid():
            rival = form.save(commit=False)
            rival.company = company
            if editing and 'website' in form.changed_data:
                rival.site_read_at = None  # read the new site next time
            rival.save()
            messages.success(request, _('تم حفظ المنافس.'))
            return redirect('competitors:list')
    analysis = CompetitorAnalysis.objects.filter(company=company).first()
    return render(request, 'insights/competitors.html', {
        'form': form, 'editing': editing, 'rivals': Competitor.objects.filter(company=company),
        'analysis': analysis, 'running': analysis and analysis.status == CompetitorAnalysis.Status.GENERATING,
    })


@company_required(edit=True)
@require_POST
def competitor_delete(request, pk):
    get_object_or_404(Competitor, pk=pk, company=request.company).delete()
    messages.success(request, _('تم حذف المنافس.'))
    return redirect('competitors:list')


@company_required(edit=True)
@require_POST
def competitor_analyse(request):
    company = request.company
    if not Competitor.objects.filter(company=company).exists():
        messages.error(request, _('أضف منافساً واحداً على الأقل.'))
        return redirect('competitors:list')
    if not CompetitorAnalysis.objects.filter(company=company, status=CompetitorAnalysis.Status.GENERATING).exists():
        analysis = CompetitorAnalysis.objects.create(company=company)
        Job.enqueue(company, Job.Kind.ANALYZE_COMPETITORS, request.user, analysis_id=analysis.pk)
    messages.success(request, _('يحلّل وكيل المنافسين الآن. أعد تحميل الصفحة بعد دقيقة.'))
    return redirect('competitors:list')
