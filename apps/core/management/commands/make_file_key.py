from django.core.management.base import BaseCommand

from apps.core.filecrypto import new_key


class Command(BaseCommand):
    help = 'Print a new master key for FILE_ENCRYPTION_KEY in secrets.json.'

    def handle(self, *args, **options):
        self.stderr.write(self.style.WARNING(
            'Put this in secrets.json as "FILE_ENCRYPTION_KEY" and keep ANOTHER COPY outside the server (a password '
            'manager). If it is lost, the encrypted files can never be read again. Do not paste it anywhere else.'))
        self.stdout.write(new_key())
