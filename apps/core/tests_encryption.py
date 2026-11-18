import io
import os
from pathlib import Path

from django.conf import settings
from django.core.exceptions import ImproperlyConfigured
from django.core.files.base import ContentFile
from django.core.management import call_command
from django.core.management.base import CommandError
from django.test import TestCase

from apps.companies.models import Company
from apps.core import filecrypto
from apps.core.storage import EncryptedStorage
from apps.core.tenancy import company_context
from apps.core.testapp.models import Paper


class CryptoTests(TestCase):
    master = os.urandom(32)

    def test_a_file_round_trips_and_is_not_readable_as_stored(self):
        blob = filecrypto.encrypt(self.master, 7, b'secret contract')
        self.assertTrue(filecrypto.is_encrypted(blob))
        self.assertNotIn(b'secret contract', blob)
        self.assertEqual(filecrypto.decrypt(self.master, 7, blob), b'secret contract')

    def test_each_encryption_is_different_and_each_company_has_its_own_key(self):
        self.assertNotEqual(filecrypto.encrypt(self.master, 7, b'x'), filecrypto.encrypt(self.master, 7, b'x'))
        self.assertNotEqual(filecrypto.company_key(self.master, 1), filecrypto.company_key(self.master, 2))
        blob = filecrypto.encrypt(self.master, 1, b'x')
        with self.assertRaises(filecrypto.CorruptFile):
            filecrypto.decrypt(self.master, 2, blob)          # another company's key opens nothing of ours

    def test_any_change_or_a_wrong_master_key_is_detected(self):
        blob = bytearray(filecrypto.encrypt(self.master, 1, b'important'))
        blob[-1] ^= 1
        with self.assertRaises(filecrypto.CorruptFile):
            filecrypto.decrypt(self.master, 1, bytes(blob))
        with self.assertRaises(filecrypto.CorruptFile):
            filecrypto.decrypt(os.urandom(32), 1, filecrypto.encrypt(self.master, 1, b'x'))

    def test_the_master_key_rules(self):
        self.assertEqual(len(filecrypto.load_key(filecrypto.new_key(), dev=False, secret_key='s')), 32)
        self.assertEqual(filecrypto.load_key('', dev=True, secret_key='s'), filecrypto.load_key('', dev=True, secret_key='s'))
        self.assertNotEqual(filecrypto.load_key('', dev=True, secret_key='a'), filecrypto.load_key('', dev=True, secret_key='b'))
        with self.assertRaises(ImproperlyConfigured):
            filecrypto.load_key('', dev=False, secret_key='s')          # production never starts without a key
        with self.assertRaises(ImproperlyConfigured):
            filecrypto.load_key('not-a-key', dev=False, secret_key='s')


class StorageTests(TestCase):
    @classmethod
    def setUpTestData(cls):
        cls.a = Company.objects.create(name='Alpha', industry='x', country='Qatar')
        cls.b = Company.objects.create(name='Beta', industry='x', country='Qatar')

    def test_a_private_file_is_encrypted_on_disk_and_read_back_plain(self):
        with company_context(self.a):
            paper = Paper.objects.create(file=ContentFile(b'the contract text', name='c.txt'))
        path = Path(paper.file.storage.path(paper.file.name))
        self.assertTrue(paper.file.name.startswith(f'{self.a.pk}/'))
        raw = path.read_bytes()
        self.assertTrue(filecrypto.is_encrypted(raw))
        self.assertNotIn(b'the contract text', raw)
        with company_context(self.a):
            self.assertEqual(Paper.objects.get().file.open().read(), b'the contract text')

    def test_the_company_comes_from_the_first_part_of_the_name(self):
        self.assertEqual(EncryptedStorage.company_of('12/papers/x.pdf'), 12)
        with self.assertRaises(ValueError):
            EncryptedStorage.company_of('papers/x.pdf')

    def test_a_file_moved_into_another_company_folder_cannot_be_read(self):
        with company_context(self.a):
            paper = Paper.objects.create(file=ContentFile(b'alpha only', name='c.txt'))
        storage = paper.file.storage
        source = Path(storage.path(paper.file.name))
        target = Path(storage.path(f'{self.b.pk}/papers/stolen.txt'))
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_bytes(source.read_bytes())
        with self.assertRaises(filecrypto.CorruptFile):
            storage.open(f'{self.b.pk}/papers/stolen.txt')


class CommandTests(TestCase):
    @classmethod
    def setUpTestData(cls):
        cls.company = Company.objects.create(name='Alpha', industry='x', country='Qatar')

    def out(self, name, *args):
        out = io.StringIO()
        call_command(name, *args, stdout=out, stderr=io.StringIO())
        return out.getvalue()

    def test_check_files_counts_encrypted_and_finds_clear_files(self):
        with company_context(self.company):
            paper = Paper.objects.create(file=ContentFile(b'one', name='a.txt'))
            clear = Paper.objects.create(file=ContentFile(b'two', name='b.txt'))
        Path(clear.file.storage.path(clear.file.name)).write_bytes(b'stored before encryption')
        self.assertIn('1 encrypted and readable; 1 still in the clear', self.out('check_files'))

    def test_encrypt_files_needs_a_backup_then_encrypts(self):
        with company_context(self.company):
            paper = Paper.objects.create(file=ContentFile(b'x', name='a.txt'))
        path = Path(paper.file.storage.path(paper.file.name))
        path.write_bytes(b'in the clear')
        self.assertIn('would be encrypted', self.out('encrypt_files'))
        with self.assertRaises(CommandError):
            call_command('encrypt_files', '--yes', stdout=io.StringIO())
        self.out('encrypt_files', '--yes', '--no-backup')
        self.assertTrue(filecrypto.is_encrypted(path.read_bytes()))
        with company_context(self.company):
            self.assertEqual(Paper.objects.get().file.open().read(), b'in the clear')

    def test_make_file_key_prints_a_valid_key(self):
        key = self.out('make_file_key').strip()
        self.assertEqual(len(filecrypto.load_key(key, dev=False, secret_key='')), 32)
        self.assertEqual(len(settings.FILE_ENCRYPTION_KEY), 32)
