import logging
from decimal import Decimal
from urllib.parse import urlencode

from django.contrib import messages
from django.db import transaction
from django.http import HttpResponse
from django.shortcuts import redirect
from django.urls import reverse
from django.utils import timezone
from django.utils.translation import gettext as _
from django.views.decorators.csrf import csrf_exempt
from django.views.decorators.http import require_POST
from enjaz_operators.gateways import GatewayError

from apps.companies.decorators import company_required
from apps.companies.operators import of_company
from apps.credits import catalog
from apps.credits.charging import add_points
from apps.credits.models import WalletTransaction

from . import gateways
from .models import Payment

logger = logging.getLogger(__name__)


@company_required(manage=True)
@require_POST
def checkout(request):
    """Start a card payment for one of the top-up packages (owner and administrators): the package's Stripe payment link
    of the company's operator when it has one, else a checkout opened through the operator's gateway."""
    operator = of_company(request.company).key
    try:
        amount = Decimal(request.POST.get('amount', ''))
        points = catalog.topup_points(amount)                       # only the packages, never an amount typed by hand
    except (ArithmeticError, ValueError):
        messages.error(request, _('Choose one of the top-up packages.'))
        return redirect('credits:wallet')
    link = gateways.payment_link(operator, amount)
    if link and gateways.webhook_gateway(operator) is not None:
        # The package's Stripe payment link, naming this payment: the webhook credits it once, at the right amount.
        payment = Payment.objects.create(company=request.company, user=request.user, amount_usd=amount, points=points,
                                         operator=operator, currency='USD')
        query = {'client_reference_id': str(payment.pk)}
        if request.user.email:
            query['prefilled_email'] = request.user.email
        return redirect(f'{link}{"&" if "?" in link else "?"}{urlencode(query)}')
    gateway = gateways.for_company(request.company)
    if gateway is None:
        messages.error(request, _('Online payment is not open yet.'))
        return redirect('credits:wallet')
    payment = Payment.objects.create(company=request.company, user=request.user, amount_usd=amount, points=points,
                                     operator=gateway.operator.key, currency='USD')
    base = request.build_absolute_uri('/').rstrip('/')     # the host the member is on, so a local run returns to itself
    try:
        done = gateway.checkout(
            payment_id=payment.pk, amount=amount, currency='USD', email=request.user.email,
            name=_('Wakeel credit: $%(amount)s') % {'amount': f'{amount:,.2f}'},
            success_url=base + reverse('credits:wallet') + '?paid=1', cancel_url=base + reverse('credits:wallet'),
            metadata={'company_id': request.company.pk})
    except GatewayError:
        payment.status = Payment.EXPIRED
        payment.save(update_fields=['status'])
        messages.error(request, _('The payment page could not be opened. Please try again.'))
        return redirect('credits:wallet')
    payment.stripe_session_id = done.reference[:120]
    payment.save(update_fields=['stripe_session_id'])
    return redirect(done.url)


@csrf_exempt
@require_POST
def webhook(request, operator):
    """The operator's gateway tells us a payment was completed (or expired). Its signature proves it, it may only settle
    a payment made through that same operator, and the credit is added once."""
    gateway = gateways.webhook_gateway(operator)
    if gateway is None:
        return HttpResponse(status=404)
    try:
        event = gateway.parse_webhook(request.body, request.headers)
    except GatewayError:
        return HttpResponse(status=400)
    if event.status == 'ignored' or not event.payment_id.isdigit():
        return HttpResponse(status=200)
    with transaction.atomic():
        payment = Payment.objects.select_for_update().filter(pk=event.payment_id, operator=operator).first()
        if payment is None or payment.status == Payment.PAID:
            return HttpResponse(status=200)                                       # unknown, another operator's, or already credited
        if event.status == 'expired':
            payment.status = Payment.EXPIRED
            payment.save(update_fields=['status'])
            return HttpResponse(status=200)
        right_amount = event.amount_minor == int(payment.amount_usd * 100) and event.currency == payment.currency
        if not right_amount:
            logger.error('Payment %s did not match: total=%s %s', payment.pk, event.amount_minor, event.currency)
            return HttpResponse(status=200)
        payment.status, payment.paid_at = Payment.PAID, timezone.now()
        payment.save(update_fields=['status', 'paid_at'])
        add_points(payment.company, payment.points, action=WalletTransaction.TOPUP, user=payment.user,
                   description=f'Card payment ${payment.amount_usd} ({payment.operator})')
    return HttpResponse(status=200)
