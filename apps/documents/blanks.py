"""The blanks of a template: {{name}} in its recipient, subject or text. Plain text replacement, never a template
engine: what a member types can not run anything."""
import re

BLANK = re.compile(r'\{\{\s*([^{}\n]{1,40}?)\s*\}\}')
MAX_VALUE = 500


def blanks(*texts):
    """The distinct blank names, in the order they first appear."""
    seen = []
    for text in texts:
        for name in BLANK.findall(text or ''):
            if name not in seen:
                seen.append(name)
    return seen


def fill(text, values):
    """Replace each blank by its value; a blank without a value stays as it is."""
    return BLANK.sub(lambda m: values.get(m.group(1), m.group(0)), text or '')
