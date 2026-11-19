from django import template
from django.utils.translation import gettext as _

register = template.Library()


@register.simple_tag(takes_context=True)
def marid_data(context) -> dict:
    """The texts Marid says, in the language of the page, and the name he greets the person with."""
    user = context['request'].user
    return {
        'name': (user.first_name or '').strip(),
        'greeting': _('At your command, %(name)s!'),
        'lines': [_('Wheee! That was fun.'), _('Back safe and sound!'), _('No wish is too small. Just ask.'),
                  _('Whoa, dizzy! Still at your service.'), _('Your lamp is shining today.'),
                  _('I will guard your work while you rest your eyes.')],
        'stop': _("Stop Marid's flights"), 'wake': _('Let Marid fly again'), 'asleep': _('Zzz… wake me when you need me.'),
    }
