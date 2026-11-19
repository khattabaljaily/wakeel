"""Sanitiser for SVG written by the AI. The result is shown to users, so only a small allow-list of drawing elements and
attributes survives: no scripts, no foreignObject, no event handlers, no external references."""
import re
from xml.etree import ElementTree as ET

from defusedxml import ElementTree as SafeET

MAX_BYTES = 300_000
SVG_NS = 'http://www.w3.org/2000/svg'
XLINK = 'http://www.w3.org/1999/xlink'

TAGS = {'svg', 'g', 'defs', 'path', 'rect', 'circle', 'ellipse', 'line', 'polyline', 'polygon', 'text', 'tspan',
        'textPath', 'linearGradient', 'radialGradient', 'stop', 'clipPath', 'title', 'desc', 'use'}
ATTRS = {'id', 'class', 'd', 'x', 'y', 'x1', 'y1', 'x2', 'y2', 'cx', 'cy', 'r', 'rx', 'ry', 'width', 'height', 'points',
         'viewBox', 'preserveAspectRatio', 'fill', 'fill-opacity', 'fill-rule', 'stroke', 'stroke-width', 'stroke-opacity',
         'stroke-linecap', 'stroke-linejoin', 'stroke-dasharray', 'opacity', 'transform', 'offset', 'stop-color',
         'stop-opacity', 'gradientUnits', 'gradientTransform', 'clip-path', 'clip-rule', 'font-family', 'font-size',
         'font-weight', 'font-style', 'text-anchor', 'dominant-baseline', 'letter-spacing', 'direction', 'unicode-bidi',
         'lang', 'xml:lang', 'xmlns', 'version', 'startOffset', 'dx', 'dy', 'rotate', 'textLength', 'lengthAdjust',
         'fx', 'fy', 'spreadMethod', 'clipPathUnits'}
BAD_VALUE = re.compile(r'(javascript:|data:|expression\(|@import|<|&#)', re.I)
EXTERNAL_URL = re.compile(r'url\(\s*[\'"]?(?!#)', re.I)


class UnsafeSVG(ValueError):
    pass


def _local(name: str) -> str:
    return name.rsplit('}', 1)[-1]


def _clean(element) -> None:
    for child in list(element):
        tag = _local(child.tag) if isinstance(child.tag, str) else ''
        if tag not in TAGS:
            element.remove(child)
            continue
        child.tag = tag
        for name in list(child.attrib):
            value = child.attrib[name]
            local = _local(name)
            if local == 'href' and tag in ('use', 'textPath'):
                if not value.startswith('#'):      # internal references only
                    del child.attrib[name]
                    continue
                child.attrib['href'] = value
                if name != 'href':
                    del child.attrib[name]
                continue
            if name not in ATTRS or BAD_VALUE.search(value) or EXTERNAL_URL.search(value):
                del child.attrib[name]
        _clean(child)
        if child.text and BAD_VALUE.search(child.text):
            child.text = ''


def sanitize(raw: str) -> str:
    """Return a safe copy of the first <svg> in `raw`; raise UnsafeSVG when there is none or it cannot be read."""
    match = re.search(r'<svg\b.*?</svg\s*>', raw or '', re.S | re.I)
    if not match:
        raise UnsafeSVG('no svg element')
    text = match.group(0)
    if len(text.encode('utf-8')) > MAX_BYTES:
        raise UnsafeSVG('too large')
    try:
        root = SafeET.fromstring(text)
    except Exception as exc:                        # malformed XML, entity tricks (defusedxml refuses them)
        raise UnsafeSVG('unreadable svg') from exc
    if _local(root.tag) != 'svg':
        raise UnsafeSVG('not an svg')
    root.tag = 'svg'
    for name in list(root.attrib):
        if name not in ATTRS or BAD_VALUE.search(root.attrib[name]):
            del root.attrib[name]
    root.set('xmlns', SVG_NS)
    if 'viewBox' not in root.attrib:
        raise UnsafeSVG('no viewBox')
    _clean(root)
    ET.register_namespace('', SVG_NS)
    return ET.tostring(root, encoding='unicode')
