import io
import shutil
import tempfile
from pathlib import Path

from django.core.files.base import ContentFile
from django.core.management import CommandError, call_command
from django.test import TestCase, override_settings

from apps.core import filecrypto
from apps.documents.models import Document, DocumentContent
from apps.content.tests import make_company
from apps.library.models import Record


class RotationTests(TestCase):
    def setUp(self):
        self.private = tempfile.mkdtemp()
        self.backup = tempfile.mkdtemp()
        self.override = override_settings(PRIVATE_ROOT=self.private)
        self.override.enable()
        self.addCleanup(lambda: (self.override.disable(), shutil.rmtree(self.private, True), shutil.rmtree(self.backup, True)))
        self.company = make_company('Alpha')
        self.record = Record(company=self.company, title='R', content_type='application/pdf')
        self.record.file.save('s.pdf', ContentFile(b'%PDF-1.4 secret file'), save=False)
        self.record.save()
        self.document = Document(company=self.company, title='T')
        self.document.body, self.document.subject = 'Secret text of the paper', 'S'
        self.document.save()
        self.new = filecrypto.new_key()

    def run_command(self, *args):
        out, err = io.StringIO(), io.StringIO()
        call_command('rotate_file_key', '--new-key', self.new, *args, stdout=out, stderr=err)
        return out.getvalue()

    def test_it_only_counts_without_yes_and_needs_a_backup_choice_with_it(self):
        text = self.run_command()
        self.assertIn('2 item(s) would be moved', text)
        raw = Path(self.record.file.path).read_bytes()
        with self.assertRaises(CommandError):
            self.run_command('--yes')
        self.assertEqual(Path(self.record.file.path).read_bytes(), raw)                 # nothing changed

    def test_files_and_sealed_texts_move_to_the_new_key_and_a_second_run_changes_nothing(self):
        from django.conf import settings
        old = settings.FILE_ENCRYPTION_KEY
        before = Path(self.record.file.path).read_bytes()
        text = self.run_command('--yes', '--backup-dir', self.backup)
        self.assertIn('2 item(s) moved', text)
        after = Path(self.record.file.path).read_bytes()
        new = filecrypto.load_key(self.new, dev=False, secret_key='')
        self.assertEqual(filecrypto.decrypt(new, self.company.pk, after), b'%PDF-1.4 secret file')
        with self.assertRaises(filecrypto.CorruptFile):
            filecrypto.decrypt(old, self.company.pk, after)
        payload = bytes(DocumentContent.all_companies.get(document=self.document).payload)
        self.assertIn(b'Secret text', filecrypto.decrypt(new, self.company.pk, payload))
        self.assertEqual((Path(self.backup) / self.record.file.name).read_bytes(), before)       # the original is kept
        self.assertTrue((Path(self.backup) / 'document-texts.json').exists())
        self.assertIn('0 item(s) moved', self.run_command('--yes', '--backup-dir', self.backup))   # resumable

    def test_the_app_reads_everything_once_it_has_the_new_key(self):
        self.run_command('--yes', '--no-backup')
        with override_settings(FILE_ENCRYPTION_KEY=filecrypto.load_key(self.new, dev=False, secret_key='')):
            self.assertEqual(Document.all_companies.get(pk=self.document.pk).body, 'Secret text of the paper')
            with Record.all_companies.get(pk=self.record.pk).file.storage.open(self.record.file.name, 'rb') as handle:
                self.assertIn(b'%PDF', handle.read())

    def test_the_same_key_is_refused(self):
        from django.conf import settings
        import base64
        self.new = base64.urlsafe_b64encode(settings.FILE_ENCRYPTION_KEY).decode()
        with self.assertRaises(CommandError):
            self.run_command()
