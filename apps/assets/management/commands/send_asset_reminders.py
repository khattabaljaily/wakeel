from django.core.management.base import BaseCommand

from apps.assets import reminders


class Command(BaseCommand):
    help = 'Read again the end dates of domains, then remind about assets due for renewal (run once a day).'

    def add_arguments(self, parser):
        parser.add_argument('--no-check', action='store_true', help='Do not read the end dates from the internet first.')

    def handle(self, *args, **options):
        if not options['no_check']:
            self.stdout.write(f'{reminders.refresh()} end dates read.')
        self.stdout.write(f'{reminders.send_due()} notifications made.')
