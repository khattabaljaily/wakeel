from django.apps import AppConfig
from django.utils.translation import gettext_lazy as _


class DocopsConfig(AppConfig):
    default_auto_field = 'django.db.models.BigAutoField'
    name = 'apps.docops'
    verbose_name = _('Document services')

    def ready(self):
        from . import signals  # noqa: F401  (connects the file clean-up)
