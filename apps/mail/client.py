"""Talking to the company's mail server: IMAP to read, SMTP to send. Nothing here knows about Django views.

Every connection goes through `net` (public addresses only, mail ports only). Folder names that come from a request are
checked against the server's own list before they reach a command, and search words are sent as IMAP literals, so
nothing a user types can add a command."""
import imaplib
import re
import smtplib
import ssl
import threading
import time
from dataclasses import dataclass, field
from email import message_from_bytes, policy
from email.message import EmailMessage
from email.utils import getaddresses, make_msgid, formatdate, parsedate_to_datetime
from html import escape

from django.utils.translation import gettext as _

from . import net
from .presets import SSL

MAX_MESSAGE = 30 * 1024 * 1024
MAX_ATTACHMENTS = 20 * 1024 * 1024
PAGE = 25
# Servers that keep a copy of what is sent through them; appending our own copy would show every message twice.
KEEPS_SENT_COPY = ('gmail.com', 'office365.com', 'outlook.com', 'yahoo.com')


class MailError(Exception):
    """Something the user can understand (shown as is)."""


class AuthFailed(MailError):
    pass


class _Imap(imaplib.IMAP4):
    def _create_socket(self, timeout):
        return net.open_socket(self.host, self.port, timeout or net.TIMEOUT)


class _ImapSSL(imaplib.IMAP4_SSL):
    def _create_socket(self, timeout):
        sock = net.open_socket(self.host, self.port, timeout or net.TIMEOUT)
        return self.ssl_context.wrap_socket(sock, server_hostname=self.host)


class _Smtp(smtplib.SMTP):
    def _get_socket(self, host, port, timeout):
        return net.open_socket(host, port, timeout)


class _SmtpSSL(smtplib.SMTP_SSL):
    def _get_socket(self, host, port, timeout):
        return self.context.wrap_socket(net.open_socket(host, port, timeout), server_hostname=self._host)


def _explain(exc):
    """A failure of the network or the server, in words for the user."""
    if isinstance(exc, MailError):
        return exc
    if isinstance(exc, net.UnsafeHost):
        return MailError(_('That mail server name or port is not allowed.'))
    if isinstance(exc, (imaplib.IMAP4.error, smtplib.SMTPAuthenticationError)):
        text = str(exc).lower()
        if any(w in text for w in ('auth', 'login', 'password', 'credentials', 'invalid')):
            return AuthFailed(_('The mail server refused the user name or password. Gmail, Outlook and Yahoo need an app password.'))
        return MailError(_('The mail server answered with an error.'))
    if isinstance(exc, TimeoutError):
        return MailError(_('The mail server took too long to answer. Some providers do this when the password is wrong: check the '
                           'mailbox password, then the server name and the port.'))
    if isinstance(exc, ssl.SSLError):
        return MailError(_('The secure connection to the mail server failed. Check the port and the security type.'))
    if isinstance(exc, (OSError, smtplib.SMTPException)):
        return MailError(_('Could not reach the mail server. Check the server name and the port.'))
    return MailError(_('The mail server did not answer as expected.'))


# ── folder names (IMAP "modified UTF-7") ───────────────────────────────────

def decode_name(raw: str) -> str:
    def part(match):
        chunk = match.group(1)
        if not chunk:
            return '&'
        import base64
        data = chunk.replace(',', '/')
        data += '=' * (-len(data) % 4)
        return base64.b64decode(data).decode('utf-16-be', 'replace')
    return re.sub(r'&([^-]*)-', part, raw)


def quote(raw: str) -> str:
    return '"' + raw.replace('\\', '\\\\').replace('"', '\\"') + '"'


ROLE_BY_NAME = {'sent': 'sent', 'sent items': 'sent', 'sent mail': 'sent', 'sent messages': 'sent', 'drafts': 'drafts', 'draft': 'drafts',
                'trash': 'trash', 'deleted items': 'trash', 'deleted messages': 'trash', 'bin': 'trash', 'junk': 'junk',
                'spam': 'junk', 'junk e-mail': 'junk', 'junk email': 'junk', 'archive': 'archive', 'archives': 'archive'}
ROLE_BY_FLAG = {'\\sent': 'sent', '\\drafts': 'drafts', '\\trash': 'trash', '\\junk': 'junk', '\\archive': 'archive'}
ROLE_ORDER = ['inbox', 'drafts', 'sent', 'archive', 'junk', 'trash']
LIST_LINE = re.compile(rb'\((?P<flags>[^)]*)\) (?P<sep>"(?:[^"\\]|\\.)*"|NIL) (?P<name>.+)$')


@dataclass
class Folder:
    raw: str
    name: str
    role: str = ''
    selectable: bool = True
    label: str = ''

    ICONS = {'inbox': 'mail', 'sent': 'send', 'drafts': 'pencil', 'archive': 'archive', 'junk': 'ban', 'trash': 'trash'}

    @property
    def icon(self):
        return self.ICONS.get(self.role, 'folder')


@dataclass
class Summary:
    uid: int
    sender: str
    sender_address: str
    to: str
    subject: str
    date: object
    seen: bool
    flagged: bool
    snippet: str = ''


@dataclass
class Attachment:
    index: int
    filename: str
    content_type: str
    size: int
    inline: bool = False


@dataclass
class Message:
    uid: int
    subject: str
    sender: str
    sender_address: str
    to: list
    cc: list
    reply_to: str
    date: object
    message_id: str
    references: str
    text: str
    html: str
    attachments: list = field(default_factory=list)
    seen: bool = True
    flagged: bool = False


def _clean(value) -> str:
    return re.sub(r'[\r\n]+', ' ', str(value or '')).strip()


def parse_summary(uid, flags, header_bytes) -> Summary:
    head = message_from_bytes(header_bytes, policy=policy.default)
    def addr(name):
        found = getaddresses([_clean(head.get(name))])
        return found[0] if found else ('', '')
    sender_name, sender_addr = addr('From')
    recipients = ', '.join(n or a for n, a in getaddresses([_clean(head.get('To'))]) if n or a)
    try:
        date = parsedate_to_datetime(head.get('Date')) if head.get('Date') else None
    except (TypeError, ValueError):
        date = None
    return Summary(uid, sender_name or sender_addr, sender_addr, recipients, _clean(head.get('Subject')) or _('(no subject)'), date,
                   '\\seen' in flags, '\\flagged' in flags)


def _body_text(part) -> str:
    try:
        return part.get_content()
    except (LookupError, UnicodeError, ValueError):
        payload = part.get_payload(decode=True) or b''
        return payload.decode('utf-8', 'replace')


def _attachment_parts(msg):
    found = []
    for part in msg.walk():
        if part.is_multipart():
            continue
        disposition = (part.get_content_disposition() or '')
        name = part.get_filename()
        is_body = part.get_content_type() in ('text/plain', 'text/html') and disposition != 'attachment' and not name
        if is_body:
            continue
        found.append(part)
    return found


def parse_message(uid, raw: bytes) -> Message:
    msg = message_from_bytes(raw, policy=policy.default)
    def addrs(name):
        return [f'{n} <{a}>' if n else a for n, a in getaddresses([_clean(msg.get(name))]) if a]
    sender_name, sender_addr = (getaddresses([_clean(msg.get('From'))]) or [('', '')])[0]
    try:
        date = parsedate_to_datetime(msg.get('Date')) if msg.get('Date') else None
    except (TypeError, ValueError):
        date = None
    html_part, text_part = msg.get_body(('html',)), msg.get_body(('plain',))
    attachments = []
    for index, part in enumerate(_attachment_parts(msg)):
        payload = part.get_payload(decode=True) or b''
        attachments.append(Attachment(index, _clean(part.get_filename()) or _('attachment'), part.get_content_type(), len(payload),
                                      inline=bool(part.get('Content-ID')) and part.get_content_disposition() != 'attachment'))
    return Message(uid, _clean(msg.get('Subject')) or _('(no subject)'), sender_name or sender_addr, sender_addr, addrs('To'),
                   addrs('Cc'), _clean(msg.get('Reply-To')), date, _clean(msg.get('Message-ID')), _clean(msg.get('References')),
                   _body_text(text_part) if text_part is not None else '', _body_text(html_part) if html_part is not None else '',
                   attachments)


def attachment_of(raw: bytes, index: int):
    msg = message_from_bytes(raw, policy=policy.default)
    parts = _attachment_parts(msg)
    if not 0 <= index < len(parts):
        return None
    part = parts[index]
    return _clean(part.get_filename()) or 'attachment', part.get_content_type(), part.get_payload(decode=True) or b''


# ── a line of the message under its subject ─────────────────────────────────
SEXP = re.compile(rb'\(|\)|"(?:[^"\\]|\\.)*"|[^\s()"]+')
SNIPPET_BYTES = 700
SNIPPET_CHARS = 150


def parse_structure(data: bytes):
    """The BODYSTRUCTURE of a message as nested lists (strings, NIL as None, numbers as text)."""
    stack, current = [], []
    for token in SEXP.findall(data):
        if token == b'(':
            stack.append(current)
            current = []
        elif token == b')':
            done, current = current, stack.pop() if stack else []
            current.append(done)
        elif token.startswith(b'"'):
            current.append(token[1:-1].decode('utf-8', 'replace').replace('\\"', '"'))
        else:
            current.append(None if token.upper() == b'NIL' else token.decode('utf-8', 'replace'))
    return current[0] if current else []


def text_part(struct, path=''):
    """Where the readable text of a message is: (path, 'plain' or 'html', charset, transfer encoding), plain preferred."""
    found = {}

    def walk(node, where):
        if not node or not isinstance(node, list):
            return
        if isinstance(node[0], list):                                # a multipart: its parts come first
            for i, child in enumerate([c for c in node if isinstance(c, list)], 1):
                walk(child, f'{where}.{i}' if where else str(i))
            return
        if len(node) >= 6 and isinstance(node[0], str) and isinstance(node[1], str) and node[0].upper() == 'TEXT':
            params = dict(zip(*[iter(x for x in (node[2] or []) if isinstance(x, str))] * 2)) if isinstance(node[2], list) else {}
            kind = node[1].lower()
            if kind in ('plain', 'html') and kind not in found:
                found[kind] = (where or '1', kind, next((v for k, v in params.items() if k.lower() == 'charset'), 'utf-8'), (node[5] or '7bit').lower())
    walk(struct, path)
    return found.get('plain') or found.get('html')


def snippet_of(raw: bytes, kind: str, charset: str, encoding: str) -> str:
    """The first words of a part: decoded as the message says, tags removed, spaces collapsed."""
    import base64
    import quopri
    try:
        if encoding == 'base64':
            if re.search(rb'[^A-Za-z0-9+/=\s]', raw):
                return ''
            body = re.sub(rb'[^A-Za-z0-9+/=]', b'', raw)
            body = base64.b64decode(body[:len(body) // 4 * 4], validate=False)
        elif encoding == 'quoted-printable':
            body = quopri.decodestring(raw)
        else:
            body = raw
        text = body.decode(charset or 'utf-8', 'replace')
    except Exception:
        return ''
    if text.count('\ufffd') > max(3, len(text) * 0.3):
        return ''
    if kind == 'html':
        text = re.sub(r'(?is)<(script|style|head|title)\b.*?(</\1>|$)', ' ', text)
        text = re.sub(r'(?s)<[^>]*>?', ' ', text)
        text = __import__('html').unescape(text)
    text = re.sub(r'https?://\S+', '', text)
    return re.sub(r'[\s\u200b\u00a0\u034f\u200c\u200d\ufeff]+', ' ', text).strip()[:SNIPPET_CHARS]


# Opening a connection costs a TLS handshake and a login (about two seconds on a far mail server), so a connection that was
# just used is kept for a few minutes and handed to the next request of the same mailbox. A connection belongs to one
# request at a time (it is taken out of the pool while in use), nothing is shared between mailboxes, and it lives only
# in this process's memory.
POOL_IDLE = 900
POOL_CHECK_AFTER = 20
POOL_MAX = 40
_pool = {}
_pool_lock = threading.Lock()


def _pool_key(account):
    return (account.pk, account.updated_at.isoformat()) if account.pk and account.updated_at else None


def _quiet_logout(conn):
    try:
        conn.logout()
    except Exception:
        pass


def drop_connections(account=None):
    """Forget the kept connections (of one mailbox, or all): after a password change, a disconnect, or in tests."""
    with _pool_lock:
        for key in [k for k in _pool if account is None or k[0] == account.pk]:
            _quiet_logout(_pool.pop(key)['conn'])


class Mailbox:
    """One IMAP session: `with Mailbox(account) as box:`. `password` overrides the stored one (for testing new settings)."""

    def __init__(self, account, password=None):
        self.account = account
        self.password = password
        self.conn = None
        self.cache = {}            # what this connection already knows (folders, the selected folder, the unread count)
        self.flags = ''
        self.failed = False

    def _take(self):
        key = _pool_key(self.account) if self.password is None else None
        if key is None:
            return False
        now = time.time()
        with _pool_lock:
            for old in [k for k, e in _pool.items() if now - e['at'] > POOL_IDLE]:
                _quiet_logout(_pool.pop(old)['conn'])
            entry = _pool.pop(key, None)
        if entry is None:
            return False
        if now - entry['at'] > POOL_CHECK_AFTER:
            try:
                entry['conn'].noop()
            except Exception:
                _quiet_logout(entry['conn'])
                return False
        self.conn, self.cache = entry['conn'], entry['cache']
        return True

    def __enter__(self):
        if self._take():
            return self
        a = self.account
        try:
            net.check_imap_port(a.imap_port)
            if a.imap_security == SSL:
                self.conn = _ImapSSL(a.imap_host, a.imap_port, ssl_context=ssl.create_default_context(), timeout=net.TIMEOUT)
            else:
                self.conn = _Imap(a.imap_host, a.imap_port, timeout=net.TIMEOUT)
                self.conn.starttls(ssl_context=ssl.create_default_context())
            self.conn.login(a.username, self.password if self.password is not None else a.get_password())
        except Exception as exc:
            self._close()
            raise _explain(exc) from exc
        return self

    def __exit__(self, exc_type, *rest):
        key = _pool_key(self.account) if self.password is None else None
        if key is None or self.conn is None or self.failed or exc_type is not None:
            return self._close()
        with _pool_lock:
            if len(_pool) >= POOL_MAX and key not in _pool:
                _quiet_logout(_pool.pop(next(iter(_pool)))['conn'])
            previous = _pool.pop(key, None)
            _pool[key] = {'conn': self.conn, 'cache': self.cache, 'at': time.time()}
        if previous is not None:
            _quiet_logout(previous['conn'])
        self.conn = None

    def _close(self):
        if self.conn is not None:
            _quiet_logout(self.conn)
            self.conn = None

    def _run(self, call, *args):
        try:
            status, data = call(*args)
        except Exception as exc:
            self.failed = True
            raise _explain(exc) from exc
        if status != 'OK':
            raise MailError(_('The mail server could not do that.'))
        return data

    # folders
    def folders(self):
        if 'folders' not in self.cache:
            found = []
            for line in self._run(self.conn.list) or []:
                if not isinstance(line, bytes) or not (m := LIST_LINE.match(line)):
                    continue
                flags = m.group('flags').decode().lower().split()
                raw = m.group('name').decode('utf-8', 'replace').strip()
                if raw.startswith('"') and raw.endswith('"'):
                    raw = re.sub(r'\\(.)', r'\1', raw[1:-1])
                name = decode_name(raw)
                role = 'inbox' if raw.upper() == 'INBOX' else next((ROLE_BY_FLAG[f] for f in flags if f in ROLE_BY_FLAG), '') \
                    or ROLE_BY_NAME.get(name.lower().rsplit('/', 1)[-1].rsplit('.', 1)[-1], '')
                found.append(Folder(raw, name, role, '\\noselect' not in flags))
            found.sort(key=lambda f: (ROLE_ORDER.index(f.role) if f.role in ROLE_ORDER else len(ROLE_ORDER), f.name.lower()))
            self.cache['folders'] = self._one_per_kind([f for f in found if f.selectable])
        return self.cache['folders']

    def _count(self, folder):
        try:
            status, data = self.conn.status(quote(folder.raw), '(MESSAGES)')
            return int(re.search(rb'MESSAGES (\d+)', data[0]).group(1)) if status == 'OK' else 0
        except Exception:
            return 0

    def _one_per_kind(self, folders):
        """Servers often have both `Sent` and `Sent Items`, `Junk` and `Spam`, `Draft` and `Drafts`. The fuller one of each
        pair stands for the kind (it comes first and gets our name); the other shows only while it still holds messages."""
        kept, by_role = [], {}
        for f in folders:
            by_role.setdefault(f.role, []).append(f)
        for f in folders:
            same = by_role[f.role]
            if not f.role or len(same) == 1:
                kept.append(f)
                continue
            counts = f.__dict__.setdefault('_n', self._count(f))
            if f is max(same, key=lambda x: x.__dict__.setdefault('_n', self._count(x))) or counts:
                kept.append(f)
        kept.sort(key=lambda f: (ROLE_ORDER.index(f.role) if f.role in ROLE_ORDER else len(ROLE_ORDER),
                                 -f.__dict__.get('_n', 0), f.name.lower()))
        return kept

    def folder(self, raw):
        """The folder with this name on the server, or None (so a request can never name something the server did not list)."""
        return next((f for f in self.folders() if f.raw == raw), None)

    def role_folder(self, role):
        return next((f for f in self.folders() if f.role == role), None)

    def unread(self, folder):
        """The unread count of a folder, remembered for a few seconds (it is shown on every page)."""
        known = self.cache.get('unread')
        if known and known[0] == folder.raw and time.time() - known[2] < 20:
            return known[1]
        try:
            status, data = self.conn.status(quote(folder.raw), '(UNSEEN)')
            count = int(re.search(rb'UNSEEN (\d+)', data[0]).group(1)) if status == 'OK' else 0
        except Exception:
            return 0
        self.cache['unread'] = (folder.raw, count, time.time())
        return count

    def _select(self, folder, readonly=False):
        """Open the folder unless this connection already has it open."""
        if self.cache.get('selected') == folder.raw:
            return
        self.cache.pop('selected', None)
        try:
            status, data = self.conn.select(quote(folder.raw), readonly)
        except Exception as exc:
            self.failed = True
            raise _explain(exc) from exc
        if status != 'OK':
            raise MailError(_('The folder could not be opened.'))
        self.cache['selected'] = folder.raw

    # messages
    def list(self, folder, page=1, query=''):
        """(summaries newest first, total matching, page)."""
        self._select(folder)
        self.cache.pop('unread', None) if query else None
        try:
            if query:
                self.conn.literal = query.encode('utf-8')
                status, data = self.conn.uid('SEARCH', 'CHARSET', 'UTF-8', 'UNDELETED', 'TEXT')
            else:
                status, data = self.conn.uid('SEARCH', None, 'UNDELETED')
        except Exception as exc:
            raise _explain(exc) from exc
        if status != 'OK':
            raise MailError(_('The search failed.'))
        uids = sorted((int(x) for x in (data[0] or b'').split()), reverse=True)
        total = len(uids)
        page = max(1, min(page, max(1, -(-total // PAGE))))
        chosen = uids[(page - 1) * PAGE:page * PAGE]
        if not chosen:
            return [], total, page
        data = self._run(self.conn.uid, 'FETCH', ','.join(map(str, chosen)), '(FLAGS BODY.PEEK[HEADER.FIELDS (FROM TO SUBJECT DATE)])')
        found, current = {}, None
        for item in data:
            if isinstance(item, tuple):
                uid = int(re.search(rb'UID (\d+)', item[0]).group(1))
                flags = (re.search(rb'FLAGS \(([^)]*)\)', item[0]) or [None, b''])[1].decode().lower()
                current = found[uid] = [flags, item[1]]
            elif isinstance(item, bytes) and current is not None and (m := re.search(rb'FLAGS \(([^)]*)\)', item)):
                current[0] = m.group(1).decode().lower()
        summaries = [parse_summary(uid, found[uid][0], found[uid][1]) for uid in chosen if uid in found]
        self._add_snippets(folder, summaries)
        return summaries, total, page

    def _add_snippets(self, folder, summaries):
        """A line of text under each subject: two more requests for the whole page (the structure, then the first words of each
        text part), and remembered, so paging back or refreshing costs nothing. It never stops the list from showing."""
        known = self.cache.setdefault('snippets', {})
        missing = [s.uid for s in summaries if (folder.raw, s.uid) not in known]
        if missing:
            try:
                data = self._run(self.conn.uid, 'FETCH', ','.join(map(str, missing)), '(BODYSTRUCTURE)')
                where, groups = {}, {}
                for item in data:
                    meta = item if isinstance(item, bytes) else None
                    if meta is None:
                        continue
                    uid = re.search(rb'UID (\d+)', meta)
                    start = meta.find(b'BODYSTRUCTURE')
                    if uid and start >= 0:
                        spec = text_part(parse_structure(meta[start + len(b'BODYSTRUCTURE'):]))
                        if spec:
                            where[int(uid.group(1))] = spec
                            groups.setdefault(spec[0], []).append(int(uid.group(1)))
                for path, uids in groups.items():
                    part = self._run(self.conn.uid, 'FETCH', ','.join(map(str, uids)), f'(BODY.PEEK[{path}]<0.{SNIPPET_BYTES}>)')
                    for item in part:
                        if isinstance(item, tuple) and (m := re.search(rb'UID (\d+)', item[0])):
                            spec = where.get(int(m.group(1)))
                            if spec:
                                known[(folder.raw, int(m.group(1)))] = snippet_of(item[1], spec[1], spec[2], spec[3])
            except (MailError, ValueError, IndexError):
                pass
            for uid in missing:
                known.setdefault((folder.raw, uid), '')
            while len(known) > 600:
                known.pop(next(iter(known)))
        for s in summaries:
            s.snippet = known.get((folder.raw, s.uid), '')

    def _raw(self, folder, uid, mark_seen=False):
        """The whole message in ONE request (each request costs a round trip to the server). Asking for the body without
        PEEK makes the server itself mark it read. A message over the limit is refused after the server has sent its size."""
        self._select(folder)
        part = 'BODY[]' if mark_seen else 'BODY.PEEK[]'
        data = self._run(self.conn.uid, 'FETCH', str(uid), f'(FLAGS RFC822.SIZE {part}<0.{MAX_MESSAGE}>)')
        item = next((x for x in data if isinstance(x, tuple)), None)
        if item is None:
            return None
        meta = item[0] + b' ' + b' '.join(x for x in data if isinstance(x, bytes))
        size = re.search(rb'RFC822\.SIZE (\d+)', meta)
        if size and int(size.group(1)) > MAX_MESSAGE:
            raise MailError(_('That message is too large to open here.'))
        found = re.search(rb'FLAGS \(([^)]*)\)', meta)
        self.flags = (found.group(1).decode().lower() if found else '')
        if mark_seen:
            self.cache.pop('unread', None)
        return item[1]

    def message(self, folder, uid, mark_seen=True):
        raw = self._raw(folder, uid, mark_seen)
        if raw is None:
            return None
        message = parse_message(uid, raw)
        message.seen, message.flagged = '\\seen' in self.flags, '\\flagged' in self.flags
        return message

    def attachment(self, folder, uid, index):
        raw = self._raw(folder, uid)
        return attachment_of(raw, index) if raw else None

    def flag(self, folder, uid, flag, on=True):
        self._select(folder)
        self.cache.pop('unread', None)
        self._run(self.conn.uid, 'STORE', str(uid), '+FLAGS' if on else '-FLAGS', f'({flag})')

    def _remove(self, uid):
        """Take a message out of the current folder: flagged deleted, and expunged when the server can expunge just that one."""
        self._run(self.conn.uid, 'STORE', str(uid), '+FLAGS', '(\\Deleted)')
        if 'UIDPLUS' in self.conn.capabilities:
            self._run(self.conn.uid, 'EXPUNGE', str(uid))

    def move(self, folder, uid, target):
        self._select(folder)
        self.cache.pop('unread', None)
        self._run(self.conn.uid, 'COPY', str(uid), quote(target.raw))
        self._remove(uid)

    def delete(self, folder, uid):
        """To the trash; for good when it is already there (or there is no trash)."""
        trash = self.role_folder('trash')
        if trash and trash.raw != folder.raw:
            return self.move(folder, uid, trash)
        self._select(folder)
        self.cache.pop('unread', None)
        self._remove(uid)

    def append_sent(self, raw: bytes):
        sent = self.role_folder('sent')
        if sent is None:
            return False
        self._run(self.conn.append, quote(sent.raw), '\\Seen', imaplib.Time2Internaldate(time.time()), raw)
        return True


def build_message(account, to, cc, bcc, subject, body, attachments=(), reply_to_message=None, html=None, logo=None):
    """The message to send. `body` is the plain text; `html` (the finished page, with the template applied) is the other
    version; `logo` is (bytes, 'image/png') for a template that shows it (referred to in the page as cid:logo)."""
    msg = EmailMessage()
    msg['From'] = account.from_header
    msg['To'] = ', '.join(to)
    if cc:
        msg['Cc'] = ', '.join(cc)
    msg['Subject'] = _clean(subject)
    msg['Date'] = formatdate(localtime=True)
    msg['Message-ID'] = make_msgid(domain=account.address.rsplit('@', 1)[-1])
    if reply_to_message is not None and reply_to_message.message_id:
        msg['In-Reply-To'] = reply_to_message.message_id
        msg['References'] = (reply_to_message.references + ' ' + reply_to_message.message_id).strip()
    msg.set_content(body)
    msg.add_alternative(html or f'<div dir="auto" style="white-space:pre-wrap">{escape(body)}</div>', subtype='html')
    if logo and html and 'cid:logo' in html:
        data, content_type = logo
        main, _s, sub = content_type.partition('/')
        msg.get_payload()[1].add_related(data, maintype=main, subtype=sub, cid='<logo>', disposition='inline', filename='logo.' + sub)
    for name, content_type, data in attachments:
        main, _s, sub = (content_type or 'application/octet-stream').partition('/')
        msg.add_attachment(data, maintype=main or 'application', subtype=sub or 'octet-stream', filename=name)
    return msg


def send(account, to, cc, bcc, subject, body, attachments=(), reply_to_message=None, html=None, logo=None):
    """Send through the company's SMTP server and keep a copy in its Sent folder. Returns True when the copy was kept."""
    if sum(len(a[2]) for a in attachments) > MAX_ATTACHMENTS:
        raise MailError(_('The attachments are larger than 20 MB together.'))
    msg = build_message(account, to, cc, bcc, subject, body, attachments, reply_to_message, html, logo)
    recipients = list(dict.fromkeys(to + cc + bcc))
    try:
        net.check_smtp_port(account.smtp_port)
        if account.smtp_security == SSL:
            server = _SmtpSSL(account.smtp_host, account.smtp_port, timeout=net.TIMEOUT, context=ssl.create_default_context())
        else:
            server = _Smtp(account.smtp_host, account.smtp_port, timeout=net.TIMEOUT)
            server.starttls(context=ssl.create_default_context())
        with server:
            server.login(account.username, account.get_password())
            server.send_message(msg, from_addr=account.address, to_addrs=recipients)
    except smtplib.SMTPRecipientsRefused as exc:
        raise MailError(_('The mail server refused these recipients: %(who)s') % {'who': ', '.join(exc.recipients)}) from exc
    except smtplib.SMTPSenderRefused as exc:
        raise MailError(_('The mail server does not allow sending from this address.')) from exc
    except Exception as exc:
        raise _explain(exc) from exc
    if any(account.smtp_host.lower().endswith(h) for h in KEEPS_SENT_COPY):
        return True
    try:
        with Mailbox(account) as box:
            return box.append_sent(msg.as_bytes())
    except MailError:
        return False


def check_settings(account, password):
    """Try the IMAP login and the SMTP login with these settings. Raises MailError with the reason."""
    with Mailbox(account, password) as box:
        box.folders()
    try:
        net.check_smtp_port(account.smtp_port)
        if account.smtp_security == SSL:
            server = _SmtpSSL(account.smtp_host, account.smtp_port, timeout=net.TIMEOUT, context=ssl.create_default_context())
        else:
            server = _Smtp(account.smtp_host, account.smtp_port, timeout=net.TIMEOUT)
            server.starttls(context=ssl.create_default_context())
        with server:
            server.login(account.username, password)
    except Exception as exc:
        err = _explain(exc)
        raise type(err)(_('Reading works, but sending does not: %(why)s') % {'why': err}) from exc
