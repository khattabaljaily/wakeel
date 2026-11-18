"""The public page a QR code opens: it says that a printed document was issued by a company through Wakeel, and shows the
whole document as it was issued, so whoever holds the paper can compare the two (a changed text is a forged paper).
The code is random and printed only on that paper. Never shown: who issued it inside the company. Rate limited per
address and kept out of search engines."""
from django.core.cache import cache
from django.http import Http404, HttpResponse
from django.shortcuts import render
from django.template.loader import render_to_string
from django.utils import translation

from apps.audit.log import client_ip

from .models import Document

LIMIT, WINDOW = 30, 60          # requests per address per minute


def verify(request, code):
    key = f'verify:{client_ip(request)}'
    cache.add(key, 0, WINDOW)
    try:
        count = cache.incr(key)
    except ValueError:
        count = 1
    if count > LIMIT:
        return HttpResponse('Too many requests. Please wait a minute.', status=429)
    document = Document.all_companies.select_related('company').filter(verify_code=code).first() if 8 <= len(code) <= 24 else None
    if document is None:
        raise Http404
    company = document.company
    with translation.override(document.language):        # the page speaks the language of the paper in hand
        response = render(request, 'documents/verify.html', {'company': company.name_for(document.language), 'document': document,
                                                             'paper': _paper(request, document, company)})
    response['X-Robots-Tag'] = 'noindex, nofollow'
    response['Cache-Control'] = 'no-store'
    return response


def _paper(request, document, company):
    """The document as it was issued: the printed page, with its images embedded (the visitor is not signed in). The QR
    itself is left out: the code is on the card above. The page goes into an iframe's srcdoc, so the template escapes it."""
    from . import views
    context = views._paper_context(request, document, embed=True, pdf=True, company=company)
    return render_to_string('documents/print.html', context, request=request)
