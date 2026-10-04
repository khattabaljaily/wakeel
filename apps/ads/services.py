"""Promotion drafts: the AI's suggestion, and the campaign created PAUSED through the Meta Marketing API."""
import datetime
import json
from decimal import Decimal, InvalidOperation

from django.conf import settings
from django.utils import timezone
from django.utils.translation import gettext_lazy as _

from apps.social.meta import MetaError, _call
from apps.social.models import SocialAccount

from .models import AdDraft

MAX_DAILY = Decimal('500')
MAX_DAYS = 30
# Country names as companies write them -> ISO codes Meta targets.
COUNTRIES = {
    'قطر': 'QA', 'السعودية': 'SA', 'المملكة العربية السعودية': 'SA', 'الإمارات': 'AE', 'الامارات': 'AE', 'السودان': 'SD',
    'مصر': 'EG', 'الكويت': 'KW', 'البحرين': 'BH', 'عمان': 'OM', 'عُمان': 'OM', 'الأردن': 'JO', 'الاردن': 'JO',
    'qatar': 'QA', 'saudi arabia': 'SA', 'uae': 'AE', 'united arab emirates': 'AE', 'sudan': 'SD', 'egypt': 'EG',
    'kuwait': 'KW', 'bahrain': 'BH', 'oman': 'OM', 'jordan': 'JO', 'united kingdom': 'GB',
}
# Currencies whose budgets Meta takes without minor units.
ZERO_DECIMAL = {'JPY', 'KRW', 'CLP', 'ISK', 'HUF', 'TWD', 'VND', 'PYG', 'IDR', 'COP', 'CRC'}


def country_code(company):
    return COUNTRIES.get((company.country or '').strip().lower()) or COUNTRIES.get((company.country or '').strip(), '')


def facebook_account(company):
    return SocialAccount.objects.filter(company=company, platform=SocialAccount.Platform.FACEBOOK).first()


def enabled(company):
    account = facebook_account(company)
    return bool(settings.META_ADS_SCOPES and account and account.user_token)


def ad_accounts(company):
    """The ad accounts the connected Facebook user can use: [{id, name, currency}]."""
    account = facebook_account(company)
    body = _call('GET', 'me/adaccounts', params={'access_token': account.user_token, 'fields': 'id,name,currency,account_status', 'limit': 50})
    return [{'id': a['id'], 'name': a.get('name') or a['id'], 'currency': a.get('currency', 'USD')}
            for a in body.get('data', []) if a.get('account_status') == 1]


def run_suggest(job):
    from apps.ai import ads as ai
    from apps.core import language
    draft = AdDraft.objects.select_related('company', 'post').get(pk=job.params['draft_id'], company=job.company)
    company = draft.company
    stats = ', '.join(f'{i.platform}: reach {i.reach}, interactions {i.engagement}' for i in draft.post.insights.all()) or 'unknown'
    try:
        result = ai.suggest(company, draft.post, stats, company.ad_account_currency or 'USD',
                            language.name(language.of_user(job.created_by) if job.created_by_id else language.of_team(company)))
    except Exception as exc:
        draft.status, draft.error = AdDraft.Status.FAILED, str(exc)
        draft.save(update_fields=['status', 'error'])
        raise
    job.add_usage(result)
    d = result.data
    try:
        draft.daily_budget = min(MAX_DAILY, max(Decimal('1'), Decimal(str(d.get('daily_budget') or 5)).quantize(Decimal('0.01'))))
    except InvalidOperation:
        draft.daily_budget = Decimal('5')
    draft.days = min(MAX_DAYS, max(1, int(d.get('days') or 7)))
    draft.age_min = min(65, max(18, int(d.get('age_min') or 18)))
    draft.age_max = min(65, max(draft.age_min, int(d.get('age_max') or 55)))
    draft.gender = d.get('gender') if d.get('gender') in AdDraft.Gender.values else AdDraft.Gender.ALL
    draft.rationale = str(d.get('rationale') or '')[:2000]
    draft.audience_notes = str(d.get('audience_notes') or '')[:2000]
    draft.countries = draft.countries or country_code(company)
    draft.status, draft.error = AdDraft.Status.SUGGESTED, ''
    draft.save()
    return _('اقتراح الترويج جاهز.')


def create_paused(draft):
    """Create campaign, ad set and ad in Meta, all PAUSED. Raises MetaError; nothing is spent until a person activates it."""
    company = draft.company
    account = facebook_account(company)
    post_id = (draft.post.external_ids or {}).get('facebook', '')
    if not (account and account.user_token and company.ad_account_id and post_id):
        raise MetaError(_('يلزم حساب فيسبوك مربوط بصلاحية الإعلانات، وحساب إعلاني مختار، ومنشور منشور على فيسبوك.'))
    countries = [c for c in draft.countries.upper().replace(',', ' ').split() if len(c) == 2]
    if not countries:
        raise MetaError(_('حدّد دولة واحدة على الأقل.'))
    token, act = account.user_token, company.ad_account_id
    minor = 1 if (company.ad_account_currency or '').upper() in ZERO_DECIMAL else 100
    name = f'Wakeel · {draft.post.title[:60]}'
    start = timezone.now() + datetime.timedelta(hours=1)
    targeting = {'geo_locations': {'countries': countries}, 'age_min': draft.age_min, 'age_max': draft.age_max}
    if draft.gender != AdDraft.Gender.ALL:
        targeting['genders'] = [1 if draft.gender == AdDraft.Gender.MALE else 2]
    if not draft.campaign_id:
        draft.campaign_id = _call('POST', f'{act}/campaigns', data={
            'name': name, 'objective': 'OUTCOME_ENGAGEMENT', 'status': 'PAUSED', 'special_ad_categories': '[]',
            'is_adset_budget_sharing_enabled': 'false', 'access_token': token})['id']
        draft.save(update_fields=['campaign_id'])
    if not draft.adset_id:
        draft.adset_id = _call('POST', f'{act}/adsets', data={
            'name': name, 'campaign_id': draft.campaign_id, 'status': 'PAUSED',
            'daily_budget': int(draft.daily_budget * minor), 'billing_event': 'IMPRESSIONS',
            'optimization_goal': 'POST_ENGAGEMENT', 'destination_type': 'ON_POST', 'bid_strategy': 'LOWEST_COST_WITHOUT_CAP',
            'start_time': start.isoformat(), 'end_time': (start + datetime.timedelta(days=draft.days)).isoformat(),
            'targeting': json.dumps(targeting), 'access_token': token})['id']
        draft.save(update_fields=['adset_id'])
    creative = _call('POST', f'{act}/adcreatives', data={'name': name, 'object_story_id': post_id, 'access_token': token})['id']
    draft.ad_id = _call('POST', f'{act}/ads', data={
        'name': name, 'adset_id': draft.adset_id, 'creative': json.dumps({'creative_id': creative}), 'status': 'PAUSED',
        'access_token': token})['id']
    draft.status, draft.error = AdDraft.Status.CREATED, ''
    draft.save(update_fields=['ad_id', 'status', 'error'])


def manager_url(draft):
    act = draft.company.ad_account_id.replace('act_', '')
    return f'https://adsmanager.facebook.com/adsmanager/manage/campaigns?act={act}&selected_campaign_ids={draft.campaign_id}'
