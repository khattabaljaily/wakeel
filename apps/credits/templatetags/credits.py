from django import template

from .. import catalog, quote as quotes

register = template.Library()


@register.simple_tag
def price(service_key, units=None):
    """The price of a service for display next to a $ sign: '0.12'. Uses the same function the charge uses."""
    return quotes.make(service_key, units).usd


@register.simple_tag
def quote(service_key, units=None):
    """The whole quote (total, lines, token) for a screen that shows the breakdown and carries the signed token."""
    return quotes.make(service_key, units)


@register.filter
def usd(points):
    return catalog.format_points(points)
