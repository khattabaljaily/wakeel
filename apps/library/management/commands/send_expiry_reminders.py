from django.core.management.base import BaseCommand

from apps.library import reminders


class Command(BaseCommand):
    help = 'Remind the owners of documents that expire soon (run once a day).'

    def handle(self, *args, **options):
        self.stdout.write(f'{reminders.send_due()} notifications made.')
