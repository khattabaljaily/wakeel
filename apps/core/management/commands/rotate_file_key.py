"""Change the master encryption key: every private file and every sealed document text is decrypted with the current
key (FILE_ENCRYPTION_KEY) and sealed again with a new one.

Safe to run again if it stops half way: an item that already opens with the new key is left alone. While it runs the
app must be stopped (files already moved to the new key cannot be read by an app that still has the old one); when
it is done, put the new key in secrets.json as FILE_ENCRYPTION_KEY, keep a copy of it OUTSIDE the server, and start
the app again. Until the old key is retired, keep it too: a backup made before the rotation needs it."""
import base64
import json
import os
import shutil
from pathlib import Path

from django.conf import settings
from django.core.management.base import BaseCommand, CommandError

from apps.core import filecrypto
from apps.core.management.commands.encrypt_files import private_fields
from apps.documents.models import DocumentContent


class Command(BaseCommand):
    help = 'Re-encrypt every private file and sealed text under a new master key. Without --yes it only counts.'

    def add_arguments(self, parser):
        parser.add_argument('--new-key', required=True, help='the new master key (see: manage.py make_file_key)')
        parser.add_argument('--yes', action='store_true', help='apply the change')
        parser.add_argument('--backup-dir', help='copy every original here before it is changed')
        parser.add_argument('--no-backup', action='store_true', help='apply without a backup (not recommended)')

    def reseal(self, blob, company, old, new):
        """The blob sealed with `new`, or None when it already is (so a second run changes nothing)."""
        try:
            filecrypto.decrypt(new, company, blob)
            return None
        except filecrypto.CorruptFile:
            pass
        plain = filecrypto.decrypt(old, company, blob) if filecrypto.is_encrypted(blob) else blob
        sealed = filecrypto.encrypt(new, company, plain)
        if filecrypto.decrypt(new, company, sealed) != plain:                        # never replace on doubt
            raise CommandError('Verification failed; nothing was changed for this item.')
        return sealed

    def handle(self, *args, **options):
        apply, backup = options['yes'], options['backup_dir']
        if apply and not backup and not options['no_backup']:
            raise CommandError('Give --backup-dir DIR (a copy of everything before it changes), or --no-backup.')
        old = settings.FILE_ENCRYPTION_KEY
        new = filecrypto.load_key(options['new_key'], dev=False, secret_key='')
        if new == old:
            raise CommandError('The new key is the same as the current one.')
        moved = already = missing = failed = 0
        for model, field in private_fields():
            for row in model._base_manager.exclude(**{field.name: ''}).iterator():
                name = getattr(row, field.name).name
                path = Path(field.storage.path(name))
                if not path.exists():
                    missing += 1
                    self.stderr.write(f'missing on disk: {model.__name__} {row.pk} {name}')
                    continue
                company = field.storage.company_of(name)
                try:
                    sealed = self.reseal(path.read_bytes(), company, old, new)
                except filecrypto.CorruptFile:
                    failed += 1
                    self.stderr.write(f'opens with neither key: {model.__name__} {row.pk} {name}')
                    continue
                if sealed is None:
                    already += 1
                    continue
                moved += 1
                if not apply:
                    continue
                if backup:
                    target = Path(backup) / name
                    target.parent.mkdir(parents=True, exist_ok=True)
                    shutil.copy2(path, target)
                temp = path.with_name(path.name + '.tmp')
                temp.write_bytes(sealed)
                os.replace(temp, path)
        texts = []
        for row in DocumentContent.all_companies.all().iterator():
            try:
                sealed = self.reseal(bytes(row.payload), row.company_id, old, new)
            except filecrypto.CorruptFile:
                failed += 1
                self.stderr.write(f'document text opens with neither key: {row.pk}')
                continue
            if sealed is None:
                already += 1
                continue
            moved += 1
            if apply:
                texts.append((row, sealed))
        if apply and texts:
            if backup:
                Path(backup).mkdir(parents=True, exist_ok=True)
                (Path(backup) / 'document-texts.json').write_text(json.dumps(
                    {row.pk: base64.b64encode(bytes(row.payload)).decode() for row, _s in texts}), encoding='utf-8')
            for row, sealed in texts:
                DocumentContent.all_companies.filter(pk=row.pk).update(payload=sealed)
        verb = 'moved to the new key' if apply else 'would be moved to the new key'
        self.stdout.write(f'{moved} item(s) {verb}; {already} already on it; {missing} missing on disk; {failed} could not be opened.')
        if failed:
            raise CommandError('Some items open with neither key: they were left alone. Find out why before going on.')
        if apply:
            self.stdout.write(self.style.SUCCESS(
                'Done. Now put the new key in secrets.json as FILE_ENCRYPTION_KEY (and keep a copy outside the server), '
                'then start the app. Run manage.py check_files to confirm.'))
        elif moved:
            self.stdout.write('Nothing changed. Stop the app, then run again with --yes --backup-dir DIR.')
