"""Add translations to a gettext .po file without opening it, then dedupe and compile it.

    python3 tools/po_add.py locale/ar/LC_MESSAGES/django.po pairs.json     # pairs.json: [["msgid", "msgstr"], ...]

Used from Python:  from tools.po_add import add; add('locale/ar/LC_MESSAGES/django.po', [('Wallet', 'المحفظة')])

An entry whose msgid already exists is skipped. `msguniq --use-first` removes any duplicate a multi-line msgid hid from the
check, and `msgfmt` writes the .mo next to the .po (the .mo files are committed in this project). Needs gettext installed."""
import json
import re
import subprocess
import sys


def _esc(value):
    return value.replace('\\', '\\\\').replace('"', '\\"').replace('\n', '\\n')


def add(path, pairs):
    text = open(path, encoding='utf-8').read()
    have = set(re.findall(r'^msgid "((?:[^"\\]|\\.)*)"$', text, re.M))
    out = []
    for msgid, msgstr in pairs:
        if _esc(msgid) in have:
            continue
        out.append(f'\nmsgid "{_esc(msgid)}"\nmsgstr "{_esc(msgstr)}"\n')
        have.add(_esc(msgid))
    if out:
        open(path, 'w', encoding='utf-8').write(text.rstrip('\n') + '\n' + ''.join(out))
    subprocess.run(['msguniq', '--use-first', '-o', path, path], check=True, stderr=subprocess.DEVNULL)
    subprocess.run(['msgfmt', '-o', path[:-3] + '.mo', path], check=True, stderr=subprocess.DEVNULL)
    return len(out)


if __name__ == '__main__':
    print(add(sys.argv[1], json.load(open(sys.argv[2], encoding='utf-8'))), 'entries added')
