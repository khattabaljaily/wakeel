from django.contrib import messages
from django.core.paginator import Paginator
from django.shortcuts import get_object_or_404, redirect, render
from django.utils.translation import gettext_lazy as _
from django.views.decorators.http import require_POST

from apps.companies.decorators import company_required
from apps.jobs.models import Job
from apps.social.meta import MetaError
from apps.social.models import SocialAccount

from . import services
from .models import InboxItem

VIEWS = {
    'new': {'status': InboxItem.Status.NEW},
    'urgent': {'status': InboxItem.Status.NEW, 'urgency__in': [InboxItem.Urgency.HIGH, InboxItem.Urgency.CRISIS]},
    'replied': {'status': InboxItem.Status.REPLIED},
    'all': {},
}


@company_required
def inbox(request):
    company = request.company
    view = request.GET.get('view') if request.GET.get('view') in VIEWS else 'new'
    items = InboxItem.objects.filter(company=company, **VIEWS[view]).select_related('post', 'replied_by')
    page = Paginator(items, 30).get_page(request.GET.get('page'))
    counts = {key: InboxItem.objects.filter(company=company, **flt).count() for key, flt in VIEWS.items() if key != 'all'}
    return render(request, 'inbox/inbox.html', {
        'page': page, 'view': view, 'counts': counts,
        'connected': SocialAccount.objects.filter(company=company).exclude(platform=SocialAccount.Platform.TIKTOK).exists(),
        'views': [('new', _('جديد')), ('urgent', _('عاجل')), ('replied', _('تم الرد')), ('all', _('الكل'))],
    })


@company_required(edit=True)
@require_POST
def item_reply(request, pk):
    item = get_object_or_404(InboxItem, pk=pk, company=request.company)
    text = request.POST.get('text', '').strip()
    if not text:
        messages.error(request, _('اكتب الرد أولاً.'))
    else:
        try:
            services.reply(item, text, request.user)
        except MetaError as exc:
            messages.error(request, str(exc))
        else:
            messages.success(request, _('تم إرسال الرد.'))
    return redirect(request.POST.get('next') or 'inbox:inbox')


@company_required(edit=True)
@require_POST
def item_dismiss(request, pk):
    item = get_object_or_404(InboxItem, pk=pk, company=request.company)
    item.status = InboxItem.Status.NEW if request.POST.get('undo') else InboxItem.Status.DISMISSED
    item.save(update_fields=['status'])
    return redirect(request.POST.get('next') or 'inbox:inbox')


@company_required(edit=True)
@require_POST
def refresh(request):
    if not Job.objects.filter(company=request.company, kind=Job.Kind.FETCH_INBOX, status__in=[Job.Status.PENDING, Job.Status.RUNNING]).exists():
        Job.enqueue(request.company, Job.Kind.FETCH_INBOX, request.user)
    messages.success(request, _('يقرأ وكيل التعليقات الجديدة الآن. أعد تحميل الصفحة بعد لحظات.'))
    return redirect('inbox:inbox')


@company_required(manage=True)
@require_POST
def auto_reply(request):
    company = request.company
    company.inbox_auto_reply = request.POST.get('on') == '1'
    company.save(update_fields=['inbox_auto_reply'])
    messages.success(request, _('تم تشغيل الرد التلقائي على الأسئلة البسيطة والإشادات.') if company.inbox_auto_reply
                     else _('تم إيقاف الرد التلقائي.'))
    return redirect('inbox:inbox')
