"""A document as a real PDF file: the same page that is printed, with everything it needs (the font, the letterhead
and the logo) embedded in it, printed by headless Chrome. Without a Chrome/Chromium on the machine the
feature is simply off (`available()` is False) and the screens keep to "Preview and print"."""
import base64
import logging
import mimetypes
import shutil
import subprocess
import tempfile
from pathlib import Path

from django.conf import settings
from django.contrib.staticfiles import finders

logger = logging.getLogger(__name__)
TIMEOUT = 60
CANDIDATES = ('google-chrome', 'google-chrome-stable', 'chromium', 'chromium-browser')


def chrome_binary():
    configured = getattr(settings, 'CHROME_BIN', '')
    if configured and Path(configured).exists():
        return configured
    for name in CANDIDATES:
        found = shutil.which(name)
        if found:
            return found
    return ''


def available() -> bool:
    return bool(chrome_binary())


def data_uri(content: bytes, mime: str) -> str:
    return f'data:{mime};base64,{base64.b64encode(content).decode()}'


def file_uri(field_file) -> str:
    """An uploaded (private, encrypted) image as a data URI, so the PDF page needs no request to the app."""
    with field_file.storage.open(field_file.name, 'rb') as handle:       # a fresh handle: the field's own may be used up
        content = handle.read()
    mime = mimetypes.guess_type(field_file.name)[0] or 'image/png'
    if content[:4] == b'<svg' or content.lstrip()[:5] == b'<?xml' or content.lstrip()[:4] == b'<svg':
        mime = 'image/svg+xml'
    return data_uri(content, mime)


def font_uri() -> str:
    path = finders.find('fonts/Almohanad-Regular.ttf')
    return data_uri(Path(path).read_bytes(), 'font/ttf') if path else ''


class PdfError(Exception):
    pass


def html_to_pdf(html: str) -> bytes:
    binary = chrome_binary()
    if not binary:
        raise PdfError('No Chrome or Chromium on this machine.')
    with tempfile.TemporaryDirectory(prefix='wk-pdf-') as folder:
        source, target = Path(folder) / 'page.html', Path(folder) / 'page.pdf'
        source.write_text(html, encoding='utf-8')
        command = [binary, '--headless=new', '--no-sandbox', '--disable-gpu', '--disable-extensions', '--no-first-run',
                   '--hide-scrollbars', '--no-pdf-header-footer', f'--user-data-dir={folder}/profile',
                   f'--print-to-pdf={target}', f'file://{source}']
        try:
            subprocess.run(command, check=True, capture_output=True, timeout=TIMEOUT)
        except (subprocess.SubprocessError, OSError) as exc:
            logger.warning('PDF printing failed: %s', exc)
            raise PdfError('The PDF could not be made.') from exc
        if not target.exists() or target.stat().st_size < 500:
            raise PdfError('The PDF could not be made.')
        return target.read_bytes()
