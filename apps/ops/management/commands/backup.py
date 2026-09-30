from django.core.management.base import BaseCommand, CommandError

from apps.ops.backup import run


class Command(BaseCommand):
    help = 'Back up the database and uploaded files (see apps.ops.backup).'

    def handle(self, *args, **opts):
        status = run()
        size = status['total_bytes'] / 1024 ** 2
        if not status['ok']:
            raise CommandError(f"Backup failed: {status['error']}")
        self.stdout.write(f"Backup done: {status['db_file']} · {status['db_runs']} DB / {status['media_runs']} media "
                          f"backups kept · {size:.1f} MB in total")
