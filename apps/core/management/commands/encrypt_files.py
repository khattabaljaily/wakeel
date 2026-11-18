"""Encrypt, in place, the private files that were stored before encryption was switched on."""
import os
import shutil
from pathlib import Path

from django.apps import apps
from django.conf import settings
from django.core.management.base import BaseCommand, CommandError
from django.db import models

from apps.core import filecrypto
from apps.core.storage import EncryptedStorage


def private_fields():
    """Every file field of every model that keeps its files in the encrypted private storage."""
    for model in apps.get_models():
        for field in model._meta.get_fields():
            if isinstance(field, models.FileField) and isinstance(field.storage, EncryptedStorage):
                yield model, field


class Command(BaseCommand):
    help = 'Encrypt private files stored in the clear. Shows what it would do; --yes applies it (needs a backup).'

    def add_arguments(self, parser):
        parser.add_argument('--yes', action='store_true', help='apply the changes')
        parser.add_argument('--backup-dir', help='copy every original here before it is changed')
        parser.add_argument('--no-backup', action='store_true', help='apply without a backup (not recommended)')

    def handle(self, *args, **options):
        apply, backup = options['yes'], options['backup_dir']
        if apply and not backup and not options['no_backup']:
            raise CommandError('Give --backup-dir DIR (a copy of every file before it changes), or --no-backup.')
        todo = already = missing = 0
        for model, field in private_fields():
            for row in model._base_manager.exclude(**{field.name: ''}).iterator():
                name = getattr(row, field.name).name
                path = Path(field.storage.path(name))
                if not path.exists():
                    missing += 1
                    self.stderr.write(f'missing on disk: {model.__name__} {row.pk} {name}')
                    continue
                raw = path.read_bytes()
                if filecrypto.is_encrypted(raw):
                    already += 1
                    continue
                todo += 1
                if not apply:
                    continue
                if backup:
                    target = Path(backup) / name
                    target.parent.mkdir(parents=True, exist_ok=True)
                    shutil.copy2(path, target)
                company = field.storage.company_of(name)
                blob = filecrypto.encrypt(settings.FILE_ENCRYPTION_KEY, company, raw)
                if filecrypto.decrypt(settings.FILE_ENCRYPTION_KEY, company, blob) != raw:          # never replace on doubt
                    raise CommandError(f'Verification failed for {name}; nothing was changed for it.')
                temp = path.with_name(path.name + '.tmp')
                temp.write_bytes(blob)
                os.replace(temp, path)
        verb = 'encrypted' if apply else 'would be encrypted'
        self.stdout.write(f'{todo} file(s) {verb}; {already} already encrypted; {missing} missing on disk.')
        if todo and not apply:
            self.stdout.write('Nothing changed. Run again with --yes --backup-dir DIR to apply.')
