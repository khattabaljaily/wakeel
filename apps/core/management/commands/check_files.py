"""Read-only: can every private file be read with the current key? Which files are still in the clear? Which are orphans?"""
from pathlib import Path

from django.conf import settings
from django.core.management.base import BaseCommand, CommandError

from apps.core import filecrypto

from .encrypt_files import private_fields


class Command(BaseCommand):
    help = 'Check that every private file decrypts with FILE_ENCRYPTION_KEY, and list the ones still in the clear.'

    def handle(self, *args, **options):
        ok = clear = broken = missing = 0
        known = set()
        for model, field in private_fields():
            for row in model._base_manager.exclude(**{field.name: ''}).iterator():
                name = getattr(row, field.name).name
                path = Path(field.storage.path(name))
                known.add(path.resolve())
                if not path.exists():
                    missing += 1
                    continue
                raw = path.read_bytes()
                if not filecrypto.is_encrypted(raw):
                    clear += 1
                    continue
                try:
                    filecrypto.decrypt(settings.FILE_ENCRYPTION_KEY, field.storage.company_of(name), raw)
                    ok += 1
                except filecrypto.CorruptFile:
                    broken += 1
                    self.stderr.write(f'CANNOT DECRYPT: {model.__name__} {row.pk} {name}')
        root = Path(settings.PRIVATE_ROOT)
        orphans = [p for p in root.rglob('*') if p.is_file() and p.resolve() not in known] if root.exists() else []
        self.stdout.write(f'{ok} encrypted and readable; {clear} still in the clear; {broken} unreadable; '
                          f'{missing} missing on disk; {len(orphans)} file(s) on disk that no record uses.')
        if broken:
            raise CommandError('Some files cannot be decrypted: wrong key, or they were changed.')
