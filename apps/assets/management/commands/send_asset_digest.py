from django.core.management.base import BaseCommand

from apps.assets import digest


class Command(BaseCommand):
    help = 'E-mail the owners and administrators the digital assets that are late or due within 30 days (run once a week).'

    def handle(self, *args, **options):
        self.stdout.write(f'{digest.send_all()} e-mails sent.')
