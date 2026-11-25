from django import template
from django.utils.safestring import mark_safe

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


@register.filter
def riyals_big(points):
    """Points as a large figure with the riyal sign set smaller beside it (a hero balance, a package)."""
    return mark_safe(catalog.money_html(points))


@register.simple_tag
def riyal_pattern():
    """The amount's shape with {n} for the number, for a script that works out a price itself: 'QAR' after it, or the Arabic
    sign on its right. The script puts its formatted number where {n} is."""
    return catalog.money_pattern()
