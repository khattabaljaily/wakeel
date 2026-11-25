from django.core.management.base import BaseCommand

from apps.money import rates, sources


class Command(BaseCommand):
    help = 'Fetch the day\'s exchange rates against the dollar (run every hour from cron; the sources change daily).'

    def handle(self, *args, **options):
        found = sources.fetch_all()
        if not found:
            self.stderr.write('No exchange rate source answered; the stored rates stay until they go stale.')
            return
        updated, disputed = rates.settle(found)
        self.stdout.write(f'{len(updated)} rates updated from {", ".join(found)}.')
        if disputed:
            self.stdout.write('Sources disagree, rate kept as it was: ' + ', '.join(disputed))
