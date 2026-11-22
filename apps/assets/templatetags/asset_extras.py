import re

from django.template import Library
from django.utils.html import conditional_escape
from django.utils.safestring import mark_safe

register = Library()
DATE = re.compile(r'\b\d{4}-\d{2}-\d{2}\b')


@register.filter
def keep_dates(text):
    """Dates written 2027-03-14 inside a sentence stay in one piece, left to right, even in a right-to-left language: otherwise the
    line may break after a hyphen and the parts may swap places."""
    return mark_safe(DATE.sub(lambda m: f'<bdi style="white-space:nowrap">{m.group(0)}</bdi>', str(conditional_escape(text))))
