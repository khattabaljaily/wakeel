from django.conf import settings
from django.utils import translation

SUPPORTED = {code for code, _ in settings.LANGUAGES}


def preferred_language(request):
    """The user's saved language, else the cookie, else Arabic (never the browser's Accept-Language)."""
    user = getattr(request, 'user', None)
    if user is not None and user.is_authenticated and user.language in SUPPORTED:
        return user.language
    cookie = request.COOKIES.get(settings.LANGUAGE_COOKIE_NAME)
    return cookie if cookie in SUPPORTED else settings.LANGUAGE_CODE


class LanguageMiddleware:
    def __init__(self, get_response):
        self.get_response = get_response

    def __call__(self, request):
        language = preferred_language(request)
        translation.activate(language)
        request.LANGUAGE_CODE = language
        response = self.get_response(request)
        response.headers.setdefault('Content-Language', language)
        return response
