from datetime import timedelta

from django.core.management.base import BaseCommand
from django.utils import timezone

from apps.assistant.models import Message

KEEP = timedelta(days=365)


class Command(BaseCommand):
    help = 'Delete the Marid conversations older than twelve months (the proposals go with their messages).'

    def handle(self, *args, **options):
        deleted, _ = Message.all_companies.filter(created_at__lt=timezone.now() - KEEP).delete()
        self.stdout.write(f'{deleted} old row(s) deleted.')
