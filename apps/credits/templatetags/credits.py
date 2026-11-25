from django import template

from .. import catalog, quote as quotes

register = template.Library()


@register.simple_tag
def price(service_key, units=None):
    """The price of a service as people read it, with the riyal: '5 ر.ق'. Uses the same function the charge uses."""
    return quotes.make(service_key, units).amount


@register.simple_tag
def quote(service_key, units=None):
    """The whole quote (total, lines, token) for a screen that shows the breakdown and carries the signed token."""
    return quotes.make(service_key, units)


@register.filter
def riyals(points):
    """Points as an amount with the riyal: 5000 -> '5 ر.ق'."""
    return catalog.money(points)


@register.simple_tag
def riyal():
    """The riyal's sign in the reader's language, for a number the page writes itself (a script that works out a price)."""
    return catalog.unit()
