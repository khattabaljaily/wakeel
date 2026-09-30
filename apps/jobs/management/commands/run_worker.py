import logging

from django.core.management.base import BaseCommand, CommandError

from apps.jobs.runner import acquire_lock, work_forever


class Command(BaseCommand):
    help = 'Run queued background jobs (AI generation, image rendering).'

    def add_arguments(self, parser):
        parser.add_argument('--once', action='store_true', help='Run the jobs queued now, then exit.')

    def handle(self, *args, **opts):
        logging.basicConfig(level=logging.INFO, format='%(asctime)s %(levelname)s %(name)s: %(message)s')
        lock = acquire_lock()
        if lock is None:
            raise CommandError('Another worker is already running (possibly inside runserver).')
        work_forever(log=self.stdout.write, once=opts['once'])
