import os

from django import template
from django.conf import settings
from django.templatetags.static import static as static_url

register = template.Library()


@register.simple_tag
def static_v(path):
    """Like {% static %}, but appends the file's mtime so browsers never
    serve a stale cached copy after an edit during development."""
    url = static_url(path)
    try:
        mtime = int(os.path.getmtime(settings.BASE_DIR / 'static' / path))
    except OSError:
        mtime = 0
    return f'{url}?v={mtime}'
