from django import forms
from django.contrib import messages
from django.shortcuts import get_object_or_404, redirect, render
from django.utils.translation import gettext_lazy as _
from django.views.decorators.http import require_POST

from apps.companies.decorators import company_required
from apps.content.models import Post
from apps.jobs.models import Job
from apps.social.meta import MetaError

from . import services
from .models import AdDraft


class DraftForm(forms.ModelForm):
    class Meta:
        model = AdDraft
        fields = ['daily_budget', 'days', 'age_min', 'age_max', 'gender', 'countries']
        widgets = {'countries': forms.TextInput(attrs={'dir': 'ltr'})}

    def clean_daily_budget(self):
        value = self.cleaned_data['daily_budget']
        if not 1 <= value <= services.MAX_DAILY:
            raise forms.ValidationError(_('بين 1 و%(max)s.') % {'max': services.MAX_DAILY})
        return value

    def clean_days(self):
        value = self.cleaned_data['days']
        if not 1 <= value <= services.MAX_DAYS:
            raise forms.ValidationError(_('بين 1 و%(max)s يوماً.') % {'max': services.MAX_DAYS})
        return value

    def clean(self):
        cleaned = super().clean()
        lo, hi = cleaned.get('age_min'), cleaned.get('age_max')
        if lo is not None and hi is not None and not 18 <= lo <= hi <= 65:
            self.add_error('age_max', _('العمر بين 18 و65، والحد الأعلى لا يقل عن الأدنى.'))
        return cleaned


def _promotable(company):
    """Published Facebook posts, best first, that can be promoted."""
    from apps.insights.services import summarize
    top = summarize(company, None, None)['top']
    ids = [c['id'] for c in top] + list(Post.objects.filter(company=company, status=Post.Status.PUBLISHED)
                                        .order_by('-published_at').values_list('pk', flat=True)[:20])
    posts = {p.pk: p for p in Post.objects.filter(pk__in=ids, company=company)}
    return [posts[i] for i in dict.fromkeys(ids) if i in posts and (posts[i].external_ids or {}).get('facebook')][:10]


@company_required
def ad_list(request):
    company = request.company
    enabled = services.enabled(company)
    accounts, account_error = [], ''
    if enabled and request.membership.can_manage:
        try:
            accounts = services.ad_accounts(company)
        except MetaError as exc:
            account_error = str(exc)
    return render(request, 'ads/list.html', {
        'drafts': AdDraft.objects.filter(company=company).select_related('post'),
        'enabled': enabled, 'accounts': accounts, 'account_error': account_error,
        'promotable': _promotable(company) if enabled else [],
    })


@company_required(manage=True)
@require_POST
def choose_account(request):
    company = request.company
    chosen = next((a for a in services.ad_accounts(company) if a['id'] == request.POST.get('account')), None)
    if chosen:
        company.ad_account_id, company.ad_account_currency = chosen['id'], chosen['currency'][:3]
        company.save(update_fields=['ad_account_id', 'ad_account_currency'])
        messages.success(request, _('تم اختيار الحساب الإعلاني.'))
    return redirect('ads:list')


@company_required(edit=True)
@require_POST
def suggest(request, post_pk):
    post = get_object_or_404(Post, pk=post_pk, company=request.company, status=Post.Status.PUBLISHED)
    draft = AdDraft.objects.create(company=request.company, post=post, created_by=request.user,
                                   countries=services.country_code(request.company))
    Job.enqueue(request.company, Job.Kind.AD_SUGGEST, request.user, draft_id=draft.pk)
    return redirect('ads:draft', pk=draft.pk)


@company_required
def draft_detail(request, pk):
    draft = get_object_or_404(AdDraft.objects.select_related('post', 'company'), pk=pk, company=request.company)
    form = DraftForm(request.POST or None, instance=draft)
    if request.method == 'POST':
        if not request.membership.can_edit or draft.status == AdDraft.Status.CREATED:
            return redirect('ads:draft', pk=draft.pk)
        if form.is_valid():
            form.save()
            messages.success(request, _('تم حفظ الإعدادات.'))
            return redirect('ads:draft', pk=draft.pk)
    return render(request, 'ads/draft.html', {
        'draft': draft, 'form': form, 'currency': request.company.ad_account_currency or '',
        'manager_url': services.manager_url(draft) if draft.campaign_id else '',
        'can_create': services.enabled(request.company) and bool(request.company.ad_account_id),
    })


@company_required(manage=True)
@require_POST
def create(request, pk):
    draft = get_object_or_404(AdDraft.objects.select_related('post', 'company'), pk=pk, company=request.company)
    if draft.status not in (AdDraft.Status.SUGGESTED, AdDraft.Status.FAILED):
        return redirect('ads:draft', pk=draft.pk)
    try:
        services.create_paused(draft)
    except MetaError as exc:
        draft.status, draft.error = AdDraft.Status.FAILED, str(exc)
        draft.save(update_fields=['status', 'error'])
        messages.error(request, str(exc))
    else:
        messages.success(request, _('أُنشئ الإعلان متوقفاً في Meta. راجعه وفعّله من مدير الإعلانات حين تكون جاهزاً.'))
    return redirect('ads:draft', pk=draft.pk)


@company_required(edit=True)
@require_POST
def delete(request, pk):
    get_object_or_404(AdDraft, pk=pk, company=request.company).delete()
    return redirect('ads:list')
