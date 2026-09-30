from django import template

from apps.content.models import Post

register = template.Library()

STATUS_CLASSES = {
    Post.Status.DRAFT: 'draft',
    Post.Status.REVIEW: 'review',
    Post.Status.APPROVED: 'approved',
    Post.Status.PUBLISHED: 'published',
}


@register.filter
def status_class(status):
    return STATUS_CLASSES.get(status, 'draft')


@register.simple_tag(takes_context=True)
def nav_active(context, *prefixes):
    path = context['request'].path
    return 'active' if any(path.startswith(p) for p in prefixes) else ''


@register.filter
def thousands(value):
    """12345 -> 12,345 (Django's intcomma adds no separator in the Arabic locale)."""
    try:
        return f'{int(value):,}'
    except (TypeError, ValueError):
        return value


@register.filter(name='abs')
def absolute(value):
    try:
        return abs(value)
    except TypeError:
        return value


@register.filter
def money(value, decimals=2):
    """Amounts in English digits with thousands separators and 2 decimals: 1234.5 -> 1,234.50.

    Kept precise where two decimals would hide the amount: a non-zero value under 0.01 (a single AI call
    often costs a fraction of a cent) shows up to 4 decimals, and `decimals` allows more for unit prices
    (money:4 -> 0.022 stays 0.022). Trailing zeros beyond the second decimal are dropped.
    """
    try:
        number = float(value)
    except (TypeError, ValueError):
        return value
    places = int(decimals)
    if number and abs(number) < 0.01:
        places = max(places, 4)
    text = f'{number:,.{places}f}'
    if places > 2:
        whole, _, fraction = text.partition('.')
        text = f'{whole}.{fraction.rstrip("0").ljust(2, "0")}'
    return text
