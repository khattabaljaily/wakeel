"""What the person who got a link sees. No sign-in: the link is the key, so it is long and random, it stops working on its
date or when cancelled, it can ask for a password, tries are counted, and every visit is written down for the owner.
The page is kept out of search engines and never cached."""
from django.core.cache import cache
from django.http import FileResponse, Http404, HttpResponse
from django.shortcuts import render
from django.utils.text import slugify
from django.utils.translation import gettext as _

from apps.core import throttle
from apps.audit.log import client_ip
from apps.documents import pdf as pdf_tools
from apps.documents import views as document_views
from apps.documents.models import Document
from apps.library.models import EXTENSIONS
from apps.library.views import IMAGE_CSP
from apps.core.tenancy import company_context

from .models import ShareAccess, ShareLink

PER_IP_MINUTE = (60, 60)
WRONG_PASSWORD = (5, 15 * 60)        # per link and address


def _headers(response):
    response['X-Robots-Tag'] = 'noindex, nofollow'
    response['Cache-Control'] = 'no-store'
    response['Referrer-Policy'] = 'no-referrer'
    response['X-Content-Type-Options'] = 'nosniff'
    return response


def _gone(request):
    """One answer for a link that never existed, ended or was cancelled, so nothing is learned by guessing."""
    return _headers(render(request, 'sharing/gone.html', status=404))


def _link(request, token):
    """The link if it works right now, else None."""
    if throttle.over(request, 'share', PER_IP_MINUTE):
        raise Http404
    link = ShareLink.all_companies.select_related('company', 'record', 'document').filter(token=token).first() if 20 <= len(token) <= 43 else None
    if link is None or link.status != 'active':
        return None
    document = link.document
    if document is not None and (document.status != Document.APPROVED or document.revoked_at):
        return None                                       # cancelled since it was shared
    return link


def _log(request, link, action):
    ShareAccess.all_companies.create(company=link.company, link=link, action=action, ip=client_ip(request),
                                   agent=request.META.get('HTTP_USER_AGENT', '')[:200])


def _unlocked(request, link):
    return not link.has_password or request.session.get(f'share:{link.token}') is True


def _company(link):
    target = link.target
    return link.company.name_for(getattr(target, 'language', None) or 'en')


def open_link(request, token):
    link = _link(request, token)
    if link is None:
        return _gone(request)
    company = _company(link)
    if not _unlocked(request, link):
        wrong = False
        key = f'throttle:share-pw:{link.pk}:{client_ip(request) or "none"}'
        if request.method == 'POST':
            if throttle.count(key) >= WRONG_PASSWORD[0]:
                return _headers(render(request, 'sharing/lock.html', {'company': company, 'title': link.title, 'blocked': True}, status=429))
            if link.password_ok(request.POST.get('password')):
                request.session[f'share:{link.token}'] = True
                throttle.clear(key)
            else:
                throttle.hit(key, WRONG_PASSWORD[1])
                _log(request, link, ShareAccess.WRONG_PASSWORD)
                wrong = True
        if not _unlocked(request, link):
            return _headers(render(request, 'sharing/lock.html', {'company': company, 'title': link.title, 'wrong': wrong},
                                   status=401 if wrong else 200))
    target = link.target
    is_image = link.record is not None and link.record.is_image
    _log(request, link, ShareAccess.VIEW)
    response = render(request, 'sharing/view.html', {
        'link': link, 'company': company, 'title': link.title, 'is_image': is_image,
        'file_url': request.path + 'file/', 'doc_type': getattr(target, 'doc_type', ''),
        'language': getattr(target, 'language', None) or request.LANGUAGE_CODE})
    return _headers(response)


def _document_pdf(request, link):
    """The issued document as the PDF a member would get, made for this link (kept ten minutes)."""
    document = link.document
    key = f'share-pdf:{link.pk}:{document.updated_at.timestamp()}'
    content = cache.get(key)
    if content is None:
        request.company = link.company                    # the page is drawn for the company that issued it
        with company_context(link.company):
            content = document_views._make_pdf(request, document, preview=True)
        cache.set(key, content, 600)
    return content


def file(request, token):
    link = _link(request, token)
    if link is None or not _unlocked(request, link):
        return _gone(request)
    download = request.GET.get('download') == '1'
    if download and not link.allow_download:
        return _headers(HttpResponse(_('Saving a copy is not allowed for this link.'), status=403))
    if link.record is not None:
        record = link.record
        name = (slugify(record.title, allow_unicode=True) or 'document') + EXTENSIONS.get(record.content_type, '')
        response = FileResponse(record.file.open('rb'), content_type=record.content_type, as_attachment=download, filename=name)
        if record.is_image:
            response['Content-Security-Policy'] = IMAGE_CSP
    else:
        if not pdf_tools.available():
            raise Http404
        try:
            content = _document_pdf(request, link)
        except pdf_tools.PdfError:
            raise Http404
        response = HttpResponse(content, content_type='application/pdf')
        name = (slugify(link.document.title, allow_unicode=True) or 'document') + '.pdf'
        response['Content-Disposition'] = f'{"attachment" if download else "inline"}; filename="{name}"'
    if download:
        _log(request, link, ShareAccess.DOWNLOAD)
    response['X-Frame-Options'] = 'SAMEORIGIN'
    return _headers(response)
