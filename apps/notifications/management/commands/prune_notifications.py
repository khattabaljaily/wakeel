from django.core.management.base import BaseCommand

from apps.notifications.services import prune


class Command(BaseCommand):
    help = "Delete old notifications: read ones after NOTIFICATION_KEEP_READ_DAYS, unread ones after NOTIFICATION_KEEP_UNREAD_DAYS. Run once a day."

    def handle(self, *args, **options):
        self.stdout.write(f'{prune()} old notification(s) deleted.')
