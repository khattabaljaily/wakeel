"""A letterhead often comes as a PDF. The page it is printed on is an image, so the first page of the PDF is turned
into one (PNG, A4 at about 150 dpi) when it is uploaded. The PDF is untrusted: it is opened by `pdftoppm` in a
throw-away folder with a time and a memory limit, and the result is checked like any other image."""
import io
import resource
import subprocess
import tempfile
from pathlib import Path

from django.core.files.uploadedfile import InMemoryUploadedFile
from pypdf import PdfReader

LONG_SIDE = 1754          # pixels of the longer side: A4 at 150 dpi
TIMEOUT = 30
MEMORY = 1024 * 1024 * 1024


class PdfNotUsable(ValueError):
    pass


def is_pdf(upload) -> bool:
    head = upload.read(5)
    upload.seek(0)
    return head == b'%PDF-'


def _limits():
    resource.setrlimit(resource.RLIMIT_AS, (MEMORY, MEMORY))
    resource.setrlimit(resource.RLIMIT_CPU, (TIMEOUT, TIMEOUT))


def first_page_png(upload):
    """The first page of the uploaded PDF as an uploaded PNG file. Raises PdfNotUsable."""
    data = upload.read()
    upload.seek(0)
    try:
        reader = PdfReader(io.BytesIO(data))
        if reader.is_encrypted or not len(reader.pages):
            raise PdfNotUsable('encrypted or empty')
    except PdfNotUsable:
        raise
    except Exception as exc:
        raise PdfNotUsable('unreadable pdf') from exc
    with tempfile.TemporaryDirectory(prefix='letterhead-') as folder:
        source, target = Path(folder, 'in.pdf'), Path(folder, 'page')
        source.write_bytes(data)
        try:
            subprocess.run(['pdftoppm', '-png', '-singlefile', '-f', '1', '-l', '1', '-scale-to', str(LONG_SIDE),
                            str(source), str(target)], check=True, timeout=TIMEOUT, capture_output=True,
                           preexec_fn=_limits)
        except (subprocess.SubprocessError, OSError) as exc:
            raise PdfNotUsable('could not draw the page') from exc
        png = target.with_suffix('.png').read_bytes()
    return InMemoryUploadedFile(io.BytesIO(png), 'letterhead', 'letterhead.png', 'image/png', len(png), None)
