from django.core.management.base import BaseCommand

from apps.notes.reminders import send_due


class Command(BaseCommand):
    help = "E-mail members the reminders of their personal notes whose time has come. Run every few minutes."

    def handle(self, *args, **options):
        self.stdout.write(f'{send_due()} reminder email(s) sent.')
