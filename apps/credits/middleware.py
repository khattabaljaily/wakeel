"""A refused payment becomes a clear answer, wherever the paid action was started: a 402 with the message for the pages
that ask with JSON (the API), a message and the wallet page for the others."""
from django.contrib import messages
from django.http import JsonResponse
from django.shortcuts import redirect
from django.urls import reverse
from django.utils.translation import gettext as _

from . import catalog
from .charging import InsufficientCredits, PriceChanged


def refusal_message(exc) -> str:
    if isinstance(exc, PriceChanged):
        return _('The price changed to $%(now)s (you were shown $%(shown)s). Nothing was charged: check it and try again.') % {
            'now': catalog.format_points(exc.now), 'shown': catalog.format_points(exc.shown)}
    return _('Your balance is not enough: this needs $%(cost)s and your balance is $%(balance)s. Top up to continue.') % {
        'cost': catalog.format_points(exc.cost), 'balance': catalog.format_points(exc.balance)}


class PaymentRefusedMiddleware:
    def __init__(self, get_response):
        self.get_response = get_response

    def __call__(self, request):
        return self.get_response(request)

    def process_exception(self, request, exception):
        if not isinstance(exception, (InsufficientCredits, PriceChanged)):
            return None
        text = refusal_message(exception)
        wallet_url = reverse('credits:wallet')
        if request.path.startswith('/api/') or request.headers.get('x-requested-with') == 'XMLHttpRequest' \
                or 'application/json' in request.headers.get('accept', ''):
            body = {'error': text, 'code': getattr(exception, 'code', 'price_changed'), 'wallet_url': wallet_url}
            if isinstance(exception, InsufficientCredits):
                body.update(needed=exception.cost, balance=exception.balance)
            else:
                body.update(shown=exception.shown, now=exception.now)
            return JsonResponse(body, status=402)
        messages.error(request, text)
        return redirect(wallet_url if isinstance(exception, InsufficientCredits) else request.META.get('HTTP_REFERER') or wallet_url)
