"""What a document is worth in dense pages, so a customer pays for what the AI really reads and writes.

Every price is set for a dense page (a full A4 page of Arabic text). Before a service runs, the text of the pages it
will read is counted with the provider's free token counter (a local estimate when it cannot be reached), and
enjaz_docai.pricing.page_units turns pages + tokens into dense pages for that service. A scan or a photo has no text to
count, so its pages count as dense ones. The size is cached, so the price shown and the price charged are the same.
"""
import hashlib
import io
import logging

from django.core.cache import cache
from enjaz_docai import pricing
from pypdf import PdfReader

from apps.ai import client
from apps.credits import catalog

logger = logging.getLogger(__name__)
MIN_CHARS_A_PAGE = 40          # less text than this on average: a scan (its pages count as dense ones)
CACHE_SECONDS = 24 * 3600


def _count_tokens(text: str) -> int:
    """The provider's free token count of `text`, else a local estimate (never below it, so never cheaper)."""
    estimate = pricing.estimate_tokens(text)
    counted = client.count_tokens(text)
    return estimate if counted is None else max(counted - 8, 1)          # the message's own few tokens


def _measure(raw: bytes, is_image: bool, max_pages: int) -> dict:
    if is_image:
        return {'text_tokens': None, 'script': ''}
    reader = PdfReader(io.BytesIO(raw))
    pages = reader.pages[:max_pages]
    text = '\n'.join((page.extract_text() or '') for page in pages)
    if len(''.join(text.split())) < MIN_CHARS_A_PAGE * max(len(pages), 1):
        return {'text_tokens': None, 'script': ''}
    return {'text_tokens': _count_tokens(text), 'script': pricing.script_of(text)}


def document_size(record, max_pages: int) -> dict:
    """{'text_tokens': int or None (a scan), 'script': 'arabic' / 'latin' / 'other' / ''} of the pages read."""
    with record.file.storage.open(record.file.name, 'rb') as handle:
        raw = handle.read()
    key = 'docops:size:%s:%s:%d' % (record.pk, hashlib.sha256(raw).hexdigest()[:16], max_pages)
    size = cache.get(key)
    if size is None:
        try:
            size = _measure(raw, record.is_image, max_pages)
        except Exception:
            logger.warning('Could not measure record %s; its pages count as dense ones', record.pk, exc_info=True)
            size = {'text_tokens': None, 'script': ''}
        cache.set(key, size, CACHE_SECONDS)
    return size


def units(service_key: str, pages: int, size: dict, target_language: str = ''):
    """The dense pages this document is worth for the service (None for a service not priced by the page)."""
    if not catalog.page_pricing(service_key):
        return None
    return pricing.page_units(catalog.service(service_key), pages, size.get('text_tokens'),
                              source_script=size.get('script') or 'latin', target_language=target_language)
