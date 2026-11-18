import io
import os

from django.conf import settings
from django.core.files import File
from django.core.files.base import ContentFile
from django.core.files.storage import FileSystemStorage

from apps.core import filecrypto


class EncryptedStorage(FileSystemStorage):
    """The private files: outside MEDIA, never served by the web server, only by a view that checks access, and
    encrypted on disk with a key of the company they belong to (the first part of every stored name is its id).
    A file stored before encryption was switched on is still read as it is, until `manage.py encrypt_files` converts it."""

    @staticmethod
    def company_of(name):
        first = str(name).replace('\\', '/').lstrip('/').split('/', 1)[0]
        if not first.isdigit():
            raise ValueError(f'A private file must live under its company id: {name!r}')
        return int(first)

    def _save(self, name, content):
        content.seek(0) if hasattr(content, 'seek') else None
        blob = filecrypto.encrypt(settings.FILE_ENCRYPTION_KEY, self.company_of(name), content.read())
        return super()._save(name, ContentFile(blob))

    def _open(self, name, mode='rb'):
        with super()._open(name, 'rb') as handle:
            blob = handle.read()
        if filecrypto.is_encrypted(blob):
            blob = filecrypto.decrypt(settings.FILE_ENCRYPTION_KEY, self.company_of(name), blob)
        # A name that is only a file name, so nothing downstream mistakes it for a path on disk.
        return File(io.BytesIO(blob), name=os.path.basename(name))


def private_storage():
    return EncryptedStorage(location=settings.PRIVATE_ROOT)
