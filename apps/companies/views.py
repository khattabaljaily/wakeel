import io
import json
import logging
import re
import time
import uuid
from concurrent.futures import ThreadPoolExecutor
from urllib.parse import urlparse

from django.conf import settings
from django.contrib import messages
from django.core.files.storage import default_storage
from django.contrib.auth.decorators import login_required
from django.core.files.base import ContentFile
from django.db import transaction
from django.http import JsonResponse
from django.shortcuts import get_object_or_404, redirect, render
from django.views.decorators.http import require_POST
from PIL import Image

from apps.ai.brand import BRAND_SCHEMA, draft_brand
from apps.ai.client import AIError

from . import subscriptions, tables
from .decorators import company_required
from .forms import CompanyForm, MediaUploadForm, MemberAddForm
from .middleware import SESSION_KEY
from .models import MediaAsset, Membership
from .scrape import FetchError, read_site, safe_get
from .visual import look_at

AUTOFILL_LOGO_DIR = 'tmp/autofill'
AUTOFILL_LOGO_RE = re.compile(r'^' + re.escape(settings.MEDIA_URL) + AUTOFILL_LOGO_DIR + r'/([0-9a-f]{32})\.png$')

logger = logging.getLogger(__name__)


def _attach_logo(request, company, form):
    """Download the logo found by the website autofill, unless the user uploaded one."""
    url = form.cleaned_data.get('logo_url')
    if not url or 'logo' in request.FILES:
        return
    try:
        local = AUTOFILL_LOGO_RE.match(urlparse(url).path)
        if local:  # captured from the site by the visual probe and kept on our side
            with default_storage.open(f'{AUTOFILL_LOGO_DIR}/{local.group(1)}.png', 'rb') as f:
                data = f.read()
        else:
            _, _, data = safe_get(url, accept='image/*', max_bytes=2 * 1024 * 1024)
        with Image.open(io.BytesIO(data)) as im:
            im.verify()
            ext = (im.format or 'png').lower()
    except (FetchError, OSError, SyntaxError, ValueError) as exc:
        logger.info('Could not use logo %s: %s', url, exc)
        return
    company.logo.save(f'{company.slug}.{ext}', ContentFile(data), save=True)


@login_required
def create(request):
    form = CompanyForm(request.POST or None, request.FILES or None)
    if request.method == 'POST' and form.is_valid():
        with transaction.atomic():
            company = form.save()
            Membership.objects.create(company=company, user=request.user, role=Membership.Role.OWNER)
        _attach_logo(request, company, form)
        request.session[SESSION_KEY] = company.pk
        if not request.user.is_superuser:
            subscriptions.signed_up(company, request.user)
            return redirect('companies:status')
        messages.success(request, f'تم إنشاء مساحة عمل «{company.name}». ابدأ الآن بإعداد خطة المحتوى الأولى.')
        return redirect('content:plan_create')
    return render(request, 'companies/create.html', {'form': form, 'first_company': request.company is None})


@login_required
def status(request):
    """Shown instead of the app while the company awaits approval, or is suspended or expired."""
    company = request.company
    if company is None:
        return redirect('companies:create')
    if company.is_usable or request.user.is_superuser:
        return redirect('core:dashboard')
    return render(request, 'companies/status.html', {'target': company})


@company_required(manage=True)
def brand(request):
    form = CompanyForm(request.POST or None, request.FILES or None, instance=request.company)
    if request.method == 'POST' and form.is_valid():
        company = form.save()
        _attach_logo(request, company, form)
        # Every design uses the brand kit, so mark all images for re-rendering.
        company.posts.update(image_stale=True)
        messages.success(request, 'تم حفظ هوية العلامة. أعد تصميم الصور لتطبيق التغييرات.')
        return redirect('companies:brand')
    return render(request, 'companies/brand.html', {'form': form})


@login_required
@require_POST
def switch(request, pk):
    membership = get_object_or_404(Membership, company_id=pk, user=request.user)
    request.session[SESSION_KEY] = membership.company_id
    return redirect(request.POST.get('next') or 'core:dashboard')


@company_required
def team(request):
    company = request.company
    form = MemberAddForm(request.POST or None, company=company)
    if request.method == 'POST':
        if not request.membership.can_manage:
            messages.error(request, 'إدارة الفريق متاحة للمالك والمديرين فقط.')
            return redirect('companies:team')
        if form.is_valid():
            Membership.objects.create(company=company, user=form.user, role=form.cleaned_data['role'])
            messages.success(request, 'تمت إضافة العضو.')
            return redirect('companies:team')
    members = list(company.memberships.select_related('user').order_by('created_at'))
    table = tables.members()
    return render(request, 'companies/team.html', {
        'form': form, 'members': members, 'roles': Membership.Role.choices,
        'table': table, 'rows': table.rows(members, request, {'roles': Membership.Role.choices}),
    })


@company_required(manage=True)
@require_POST
def member_update(request, pk):
    member = get_object_or_404(Membership, pk=pk, company=request.company)
    if member.role == Membership.Role.OWNER:
        messages.error(request, 'لا يمكن تعديل صلاحيات مالك الشركة أو إزالته.')
    elif request.POST.get('action') == 'remove':
        member.delete()
        messages.success(request, 'تمت إزالة العضو.')
    elif request.POST.get('role') in (Membership.Role.ADMIN, Membership.Role.EDITOR, Membership.Role.VIEWER):
        member.role = request.POST['role']
        member.save(update_fields=['role'])
        messages.success(request, 'تم تحديث الدور.')
    return redirect('companies:team')


@company_required
def media(request):
    form = MediaUploadForm(request.POST or None, request.FILES or None)
    if request.method == 'POST':
        if not request.membership.can_edit:
            messages.error(request, 'صلاحيتك في هذه الشركة للمشاهدة فقط.')
            return redirect('companies:media')
        files = request.FILES.getlist('file')
        if files:
            added = 0
            for f in files:
                single = MediaUploadForm({'title': request.POST.get('title', ''), 'tags': request.POST.get('tags', '')}, {'file': f})
                if single.is_valid():
                    asset = single.save(commit=False)
                    asset.company, asset.uploaded_by = request.company, request.user
                    asset.save()
                    added += 1
            messages.success(request, f'تم رفع {added} صورة.')
            return redirect('companies:media')
    assets = MediaAsset.objects.filter(company=request.company)
    return render(request, 'companies/media.html', {'form': form, 'assets': assets})


@company_required(edit=True)
@require_POST
def media_delete(request, pk):
    get_object_or_404(MediaAsset, pk=pk, company=request.company).delete()
    messages.success(request, 'تم حذف الصورة.')
    return redirect('companies:media')


@login_required
@require_POST
def autofill(request):
    """Read a website and return a draft brand kit for the form to fill in."""
    try:
        url = json.loads(request.body or b'{}').get('url', '')
    except json.JSONDecodeError:
        url = ''
    if not url.strip():
        return JsonResponse({'error': 'أدخل رابط الموقع أولاً.'}, status=400)
    try:
        site = read_site(url)
    except FetchError as exc:
        return JsonResponse({'error': str(exc)}, status=400)
    if len(site['text']) < 200:
        return JsonResponse({'error': 'لم نجد نصوصاً كافية في الموقع لفهم نشاط الشركة. املأ الحقول يدوياً.'}, status=400)
    # The visual probe (logo + colours through headless Chrome) runs while the AI reads the text.
    with ThreadPoolExecutor(max_workers=1) as pool:
        visuals = pool.submit(look_at, site['url'])
        try:
            result = draft_brand(site)
        except AIError as exc:
            return JsonResponse({'error': str(exc)}, status=400)
        visuals = visuals.result()

    enums = {k: v['enum'] for k, v in BRAND_SCHEMA['properties'].items() if 'enum' in v}
    fields = {}
    for key, value in result.data.items():
        value = str(value or '').strip()
        if key in BRAND_SCHEMA['properties'] and value and (key not in enums or value in enums[key]):
            fields[key] = value
    fields.update(site['contacts'])
    fields['website'] = site['url'].rstrip('/')
    tz = guess_timezone(fields.get('country'), [fields.get('phone'), fields.get('whatsapp')])
    if tz:
        fields['timezone'] = tz
        fields.setdefault('country', TIMEZONE_COUNTRY[tz])
    logo_url = _keep_logo(visuals['logo_png']) if visuals['logo_png'] else site['logo_url']
    return JsonResponse({'fields': fields, 'colors': visuals['colors'] or site['colors'], 'logo_url': logo_url})


# Country (as the AI writes it, Arabic or English) or phone prefix -> timezone choice.
COUNTRY_TIMEZONES = {
    'Africa/Khartoum': ('السودان', 'sudan'),
    'Asia/Qatar': ('قطر', 'qatar'),
    'Asia/Riyadh': ('السعودية', 'saudi'),
    'Asia/Dubai': ('الإمارات', 'emirates', 'uae'),
    'Africa/Cairo': ('مصر', 'egypt'),
    'Asia/Kuwait': ('الكويت', 'kuwait'),
    'Asia/Muscat': ('عمان', 'عُمان', 'oman'),
    'Asia/Bahrain': ('البحرين', 'bahrain'),
    'Asia/Amman': ('الأردن', 'jordan'),
    'Europe/London': ('المملكة المتحدة', 'بريطانيا', 'united kingdom', 'england', 'britain'),
}
PHONE_TIMEZONES = {'249': 'Africa/Khartoum', '974': 'Asia/Qatar', '966': 'Asia/Riyadh', '971': 'Asia/Dubai',
                   '965': 'Asia/Kuwait', '968': 'Asia/Muscat', '973': 'Asia/Bahrain', '962': 'Asia/Amman',
                   '20': 'Africa/Cairo', '44': 'Europe/London'}
TIMEZONE_COUNTRY = {'Africa/Khartoum': 'السودان', 'Asia/Qatar': 'قطر', 'Asia/Riyadh': 'السعودية', 'Asia/Dubai': 'الإمارات',
                    'Africa/Cairo': 'مصر', 'Asia/Kuwait': 'الكويت', 'Asia/Muscat': 'عُمان', 'Asia/Bahrain': 'البحرين',
                    'Asia/Amman': 'الأردن', 'Europe/London': 'المملكة المتحدة'}


def guess_timezone(country, phones):
    """Timezone from the country name, else from the international prefix of a phone number."""
    name = (country or '').strip().lower()
    for tz, names in COUNTRY_TIMEZONES.items():
        if name and any(n in name for n in names):
            return tz
    for phone in phones:
        digits = re.sub(r'\D', '', phone or '').lstrip('0')
        for prefix in sorted(PHONE_TIMEZONES, key=len, reverse=True):
            if digits.startswith(prefix) and len(digits) > 8:
                return PHONE_TIMEZONES[prefix]
    return ''


def _keep_logo(png):
    """Store a captured logo until the form is saved; clears captures older than a day."""
    try:
        _, names = default_storage.listdir(AUTOFILL_LOGO_DIR)
    except FileNotFoundError:
        names = []
    for name in names:
        path = f'{AUTOFILL_LOGO_DIR}/{name}'
        if time.time() - default_storage.get_modified_time(path).timestamp() > 86400:
            default_storage.delete(path)
    name = default_storage.save(f'{AUTOFILL_LOGO_DIR}/{uuid.uuid4().hex}.png', ContentFile(png))
    return default_storage.url(name)


@company_required(manage=True)
@require_POST
def delete_company(request):
    """Delete the current company and everything in it. Owner only; the name must be typed to confirm."""
    company = request.company
    if request.membership.role != Membership.Role.OWNER:
        messages.error(request, 'حذف الشركة متاح لمالكها فقط.')
        return redirect('companies:brand')
    if request.POST.get('confirm_name', '').strip() != company.name.strip():
        messages.error(request, 'الاسم المكتوب لا يطابق اسم الشركة، فلم يُحذف شيء.')
        return redirect('companies:brand')
    name = company.name
    company.delete()
    request.session.pop(SESSION_KEY, None)
    messages.success(request, f'تم حذف «{name}» وكل بياناتها نهائياً.')
    return redirect('core:dashboard')


@company_required
@require_POST
def leave_company(request):
    if request.membership.role == Membership.Role.OWNER:
        messages.error(request, 'لا يمكن لمالك الشركة مغادرتها. يمكنك حذف الشركة من صفحة هوية العلامة.')
        return redirect('companies:team')
    name = request.company.name
    request.membership.delete()
    request.session.pop(SESSION_KEY, None)
    messages.success(request, f'غادرت «{name}».')
    return redirect('core:dashboard')

