import io
import re

import qrcode
import qrcode.image.svg


def svg(url: str) -> str:
    """The QR code of `url` as an inline SVG string (made here from our own address, so it is safe to print as is)."""
    image = qrcode.make(url, image_factory=qrcode.image.svg.SvgPathImage, box_size=10, border=0,
                        error_correction=qrcode.constants.ERROR_CORRECT_M)
    buffer = io.BytesIO()
    image.save(buffer)
    text = buffer.getvalue().decode('utf-8')
    text = re.sub(r'^<\?xml[^>]*\?>\s*', '', text)
    return re.sub(r'<svg width="[^"]*" height="[^"]*"', '<svg width="100%" height="100%"', text, count=1)
