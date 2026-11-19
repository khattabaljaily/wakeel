from django import template

from ..models import Operation
from ..services import KINDS

register = template.Library()


@register.inclusion_tag('docops/panel.html', takes_context=True)
def docops_panel(context, record):
    """The AI services of one library document (each opens its options and prices) and the results so far."""
    request = context['request']
    return {'request': request, 'membership': request.membership, 'record': record, 'kinds': KINDS, 'results': Operation.objects.filter(record=record),
            }
