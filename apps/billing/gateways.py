"""The payment gateway of a company: its operator's (enjaz-operators), built with that operator's keys from
secrets.json "GATEWAYS". The old "STRIPE" block stays valid as JOVIA's keys. A gateway without keys (or one this app
cannot drive yet) means no online top-up for that company: the balance can still be added from the console."""
from django.conf import settings
from enjaz_operators import gateways, registry

from apps.companies.operators import PRODUCT, of_company


def keys_for(key):
    return dict((getattr(settings, 'GATEWAY_KEYS', {}) or {}).get(key) or {})


def for_operator(key):
    """The gateway of operator `key` for MyDocHub, or None when it cannot take payments here yet."""
    try:
        op = registry.get(PRODUCT, key)
    except registry.RegistryError:
        return None
    gateway = gateways.for_operator(op, keys_for(key))
    return gateway if isinstance(gateway, gateways.StripeGateway) else None    # a manual gateway needs its own pages first


def for_company(company):
    return for_operator(of_company(company).key)


# ── Stripe payment links (settings.PAYMENT_LINKS): no secret key, only the webhook's ─────────────────────────────────
def payment_link(key, amount):
    """The operator's payment link for a package (Decimal USD), or '' when it has none."""
    links = (getattr(settings, 'PAYMENT_LINKS', {}) or {}).get(key) or {}
    return links.get(f'{amount.normalize():f}', '') or links.get(str(amount), '')


def webhook_gateway(key):
    """The Stripe gateway that reads operator `key`'s webhooks: the full gateway, or, for payment links, one built with
    the webhook secret alone. None when the operator has neither."""
    gateway = for_operator(key)
    if gateway is not None:
        return gateway
    try:
        op = registry.get(PRODUCT, key)
    except registry.RegistryError:
        return None
    keys = keys_for(key)
    if op.gateway != 'stripe' or not keys.get('webhook_secret') or not any((settings.PAYMENT_LINKS.get(key) or {}).values()):
        return None
    return gateways.StripeGateway(op, keys)


def payments_open(company):
    """Whether the company can top up by card: through its operator's API checkout or its payment links."""
    key = of_company(company).key
    return for_operator(key) is not None or webhook_gateway(key) is not None
