"""Where a document's text may go on a letterhead: below its header and above its footer. Found from the image itself
(rows that carry ink, ignoring the coloured side bands), so every company's letterhead gets the right margins without
anybody measuring. Falls back to fixed margins when the page has no clear empty band (a watermark, a frame)."""
import logging

from django.core.cache import cache
from PIL import Image

logger = logging.getLogger(__name__)
A4_MM = 297
DEFAULT = (52, 46)            # top, bottom in mm when nothing can be found
GAP = 0.035                   # an empty band this tall (of the page) separates the header from the text area
INK = 235                     # a pixel darker than this carries ink
MIN_ROW = 0.004               # share of the row's pixels that makes it an inked row


def _inked_rows(image):
    small = image.convert('L')
    small = small.resize((240, max(1, round(240 * small.height / small.width))))
    w, h = small.size
    left, right = int(w * 0.06), int(w * 0.90)               # the side bands (a coloured stripe) are not content
    pixels = small.load()
    return [sum(1 for x in range(left, right) if pixels[x, y] < INK) / (right - left) >= MIN_ROW for y in range(h)]


def _margins(image):
    rows = _inked_rows(image)
    h = len(rows)
    gap = max(2, round(h * GAP))
    top_zone, bottom_zone = int(h * 0.45), int(h * 0.60)
    header_end = None                                         # last inked row of the header block
    y, last = 0, None
    while y < top_zone:
        if rows[y]:
            last = y
        elif last is not None and not any(rows[y:y + gap]):
            header_end = last
            break
        y += 1
    footer_start = None                                       # first inked row of the footer block
    y, last = h - 1, None
    while y > bottom_zone:
        if rows[y]:
            last = y
        elif last is not None and not any(rows[max(0, y - gap + 1):y + 1]):
            footer_start = last
            break
        y -= 1
    top = DEFAULT[0] if header_end is None else round((header_end + 1) / h * A4_MM + 9)
    if header_end is None and not any(rows[:top_zone]):
        top = 18                                              # no header at all
    bottom = DEFAULT[1] if footer_start is None else round((h - footer_start) / h * A4_MM + 10)
    if footer_start is None and not any(rows[bottom_zone:]):
        bottom = 22
    return max(14, min(top, 120)), max(14, min(bottom, 80))


def margins(field_file):
    """(top_mm, bottom_mm) of the text area of a letterhead file; cached by the file's name."""
    key = f'safearea:{field_file.name}'
    found = cache.get(key)
    if found:
        return found
    try:
        with field_file.storage.open(field_file.name, 'rb') as handle:
            found = _margins(Image.open(handle))
    except Exception:
        logger.warning('Could not measure the letterhead %s', field_file.name, exc_info=True)
        return DEFAULT
    cache.set(key, found, 24 * 3600)
    return found
