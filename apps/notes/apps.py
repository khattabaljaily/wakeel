from django.apps import AppConfig


class NotesConfig(AppConfig):
    default_auto_field = 'django.db.models.BigAutoField'
    name = 'apps.notes'

    def ready(self):
        from apps.notifications.registry import collector

        from . import reminders
        collector(reminders.collect)
