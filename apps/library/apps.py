from django.apps import AppConfig
from django.utils.translation import gettext_lazy as _


class LibraryConfig(AppConfig):
    default_auto_field = 'django.db.models.BigAutoField'
    name = 'apps.library'
    verbose_name = _('Library')

    def ready(self):
        from . import signals  # noqa: F401  (connects the file clean-up)
