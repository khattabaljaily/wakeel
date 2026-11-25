from django.conf import settings


def interface_languages(request):
    """The languages the screens come in (the language menu lists these, not every language a document can be written in)."""
    return {'INTERFACE_LANGUAGES': settings.INTERFACE_LANGUAGES}
