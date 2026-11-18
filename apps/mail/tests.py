import re
from email.message import EmailMessage
from unittest import mock

from django.conf import settings
from django.core.cache import cache
from django.test import SimpleTestCase, TestCase, override_settings
from django.urls import reverse

from apps.audit.models import AuditEvent
from apps.companies.models import Company, Membership
from apps.content.tests import make_company, make_user

from . import client, htmlsafe, net, presets
from .models import MailAccount


def raw_message(subject='Hello', sender='Ann <ann@client.com>', body='Hi there', html=None, attach=None, to='info@acme.com'):
    msg = EmailMessage()
    msg['From'], msg['To'], msg['Subject'], msg['Message-ID'] = sender, to, subject, '<m1@client.com>'
    msg['Date'] = 'Mon, 02 Nov 2026 10:00:00 +0000'
    msg.set_content(body)
    if html:
        msg.add_alternative(html, subtype='html')
    if attach:
        msg.add_attachment(attach, maintype='application', subtype='pdf', filename='offer.pdf')
    return msg.as_bytes()


def fake_structure(raw):
    import email
    msg = email.message_from_bytes(raw)

    def one(part):
        enc = part.get('Content-Transfer-Encoding', '7bit')
        if part.is_multipart():
            return '(' + ''.join(one(p) for p in part.get_payload()) + f' "{part.get_content_subtype().upper()}")'
        main, sub = part.get_content_maintype().upper(), part.get_content_subtype().upper()
        charset = part.get_content_charset() or 'us-ascii'
        return f'("{main}" "{sub}" ("CHARSET" "{charset}") NIL NIL "{enc}" 100 5)'
    return one(msg)


def fake_part(raw, path):
    import email
    part = email.message_from_bytes(raw)
    for index in path.split('.'):
        part = part.get_payload()[int(index) - 1] if part.is_multipart() else part
    return part.get_payload().encode() if isinstance(part.get_payload(), str) else b''


class FakeServer:
    """What a mail server keeps and what the app sent to it; stands in for imaplib and smtplib."""

    def __init__(self):
        self.folders = {'INBOX': {}, 'Sent': {}, 'Trash': {}, 'Archive': {}}
        self.flags = {}
        self.sent = []
        self.appended = []
        self.fail_login = False
        self.logins = []

    def add(self, uid, raw, folder='INBOX', flags=''):
        self.folders[folder][uid] = raw
        self.flags[(folder, uid)] = set(flags.split())


class FakeImap:
    capabilities = ('IMAP4REV1', 'UIDPLUS')

    def __init__(self, server):
        self.server, self.current, self.literal = server, None, None

    def login(self, user, password):
        self.server.logins.append((user, password))
        if self.server.fail_login:
            import imaplib
            raise imaplib.IMAP4.error('[AUTHENTICATIONFAILED] Invalid credentials')

    def logout(self):
        return 'BYE', []

    def list(self):
        special = {'Trash': '\\Trash', 'Archive': '\\Archive'}
        return 'OK', [f'({special.get(name, "")}) "/" "{name}"'.encode() for name in self.server.folders]

    def status(self, folder, what):
        name = folder.strip('"')
        if 'MESSAGES' in what:
            return 'OK', [f'{name} (MESSAGES {len(self.server.folders[name])})'.encode()]
        n = sum(1 for u in self.server.folders[name] if '\\Seen' not in self.server.flags[(name, u)])
        return 'OK', [f'{name} (UNSEEN {n})'.encode()]

    def select(self, folder, readonly=False):
        self.current = folder.strip('"')
        return 'OK', [b'1']

    def append(self, folder, flags, date, raw):
        self.server.appended.append((folder.strip('"'), raw))
        return 'OK', []

    def uid(self, command, *args):
        s, box = self.server, self.current
        if command == 'SEARCH':
            uids = [u for u in s.folders[box] if '\\Deleted' not in s.flags[(box, u)]]
            return 'OK', [' '.join(map(str, uids)).encode()]
        if command == 'FETCH':
            wanted = [int(x) for x in args[0].split(',')]
            what = args[1]
            out = []
            for u in wanted:
                raw = s.folders[box].get(u)
                if raw is None:
                    continue
                flags = ' '.join(sorted(s.flags[(box, u)]))
                if 'BODY[]' in what or 'BODY.PEEK[]' in what:
                    if 'BODY[]' in what:
                        s.flags[(box, u)].add('\\Seen')                 # asking without PEEK marks it read
                    out.append((f'{u} (UID {u} FLAGS ({flags}) RFC822.SIZE {len(raw)} BODY[]<0> {{{len(raw)}}}'.encode(), raw))
                    out.append(b')')
                elif 'BODYSTRUCTURE' in what:
                    out.append(f'{u} (UID {u} BODYSTRUCTURE {fake_structure(raw)})'.encode())
                elif re.search(r'BODY\.PEEK\[[\d.]+\]<0\.\d+>', what):
                    path = re.search(r'\[([\d.]+)\]', what).group(1)
                    payload = fake_part(raw, path)
                    out.append((f'{u} (UID {u} BODY[{path}]<0> {{{len(payload)}}}'.encode(), payload))
                    out.append(b')')
                elif 'HEADER.FIELDS' in what:
                    head = raw.split(b'\n\n', 1)[0] + b'\r\n\r\n'
                    out.append((f'{u} (UID {u} FLAGS ({flags}) BODY[HEADER.FIELDS (FROM TO SUBJECT DATE)] {{{len(head)}}}'.encode(), head))
                    out.append(b')')
            return 'OK', out
        if command == 'STORE':
            u, op, flag = int(args[0]), args[1], args[2].strip('()')
            (s.flags[(box, u)].add if op == '+FLAGS' else s.flags[(box, u)].discard)(flag)
            return 'OK', []
        if command == 'COPY':
            u, target = int(args[0]), args[1].strip('"')
            s.add(u + 1000, s.folders[box][u], target)
            return 'OK', []
        if command == 'EXPUNGE':
            u = int(args[0])
            s.folders[box].pop(u, None)
            return 'OK', []
        raise AssertionError(command)


class FakeSmtp:
    def __init__(self, server):
        self.server = server

    def __enter__(self):
        return self

    def __exit__(self, *a):
        return False

    def login(self, user, password):
        if self.server.fail_login:
            import smtplib
            raise smtplib.SMTPAuthenticationError(535, b'bad')

    def send_message(self, msg, from_addr, to_addrs):
        self.server.sent.append((msg, from_addr, to_addrs))

    def starttls(self, **kw):
        pass


class NetTests(SimpleTestCase):
    @override_settings(MAIL_ALLOW_PRIVATE_HOSTS=False)
    def test_private_and_loopback_servers_are_refused(self):
        for host in ('127.0.0.1', 'localhost', '10.0.0.5', '192.168.1.1', '169.254.169.254', '::1'):
            with self.assertRaises(net.UnsafeHost, msg=host):
                net.public_address(host, 993)

    def test_only_mail_ports(self):
        for port in (22, 80, 3306, 6379):
            with self.assertRaises(net.UnsafeHost):
                net.check_imap_port(port)
                net.check_smtp_port(port)
        net.check_imap_port(993)
        net.check_smtp_port(587)

    @override_settings(MAIL_ALLOW_PRIVATE_HOSTS=False)
    def test_a_name_with_odd_characters_is_refused(self):
        for host in ('evil.com/x', 'a b.com', 'user@host.com', ''):
            with self.assertRaises(net.UnsafeHost):
                net.public_address(host, 993)


    @override_settings(MAIL_ALLOW_PRIVATE_HOSTS=False)
    def test_the_connection_classes_never_reach_a_private_address(self):
        for cls, port in ((client._ImapSSL, 993), (client._Imap, 143), (client._SmtpSSL, 465), (client._Smtp, 587)):
            with self.assertRaises(net.UnsafeHost, msg=cls.__name__):
                cls('127.0.0.1', port)


class PresetsTests(SimpleTestCase):
    def test_known_and_unknown_domains(self):
        self.assertEqual(presets.guess('x@gmail.com').imap_host, 'imap.gmail.com')
        self.assertEqual(presets.guess('x@outlook.com').smtp_port, 587)
        with mock.patch.object(presets, 'mx_hosts', return_value=[]):
            other = presets.guess('info@acme.sd')
        self.assertEqual((other.imap_host, other.smtp_host, other.imap_port, other.smtp_port), ('mail.acme.sd', 'mail.acme.sd', 993, 465))


    def test_a_company_domain_is_read_from_its_mx_records(self):
        with mock.patch.object(presets, 'mx_hosts', return_value=['mx1.privateemail.com']):
            found = presets.guess('info@enjaztechnology.com')
        self.assertEqual((found.imap_host, found.smtp_host, found.smtp_port), ('mail.privateemail.com', 'mail.privateemail.com', 465))
        with mock.patch.object(presets, 'mx_hosts', return_value=['aspmx.l.google.com']):
            self.assertEqual(presets.guess('x@acme.com').imap_host, 'imap.gmail.com')


class HtmlSafeTests(SimpleTestCase):
    def test_dangerous_things_do_not_survive(self):
        out, images = htmlsafe.clean(
            '<p onclick="x()" style="color:red;background:url(http://t/p.gif)">Hi</p><script>alert(1)</script><img src="http://t/p.gif">'
            '<a href="javascript:alert(1)">bad</a><a href="https://ok.com/a">ok</a><iframe src="//x"></iframe><form><input></form>')
        self.assertNotIn('script', out)
        self.assertNotIn('onclick', out)
        self.assertNotIn('url(', out)
        self.assertNotIn('javascript', out)
        self.assertNotIn('<img', out)
        self.assertNotIn('iframe', out)
        self.assertIn('href="https://ok.com/a"', out)
        self.assertIn('rel="noopener noreferrer nofollow"', out)
        self.assertEqual(images, 1)

    def test_text_is_escaped_and_links_made(self):
        out = htmlsafe.from_text('<b>x</b> see https://a.com/b?c=1&d=2')
        self.assertIn('&lt;b&gt;', out)
        self.assertIn('<a href="https://a.com/b?c=1&amp;d=2"', out)

    def test_frame_forbids_scripts_and_outside_requests(self):
        doc = htmlsafe.frame_document('<p>x</p>')
        self.assertIn("default-src 'none'", doc)


class ParseTests(SimpleTestCase):
    def test_arabic_subject_sender_attachment(self):
        raw = raw_message(subject='عرض سعر', sender='"سارة" <sara@client.com>', body='مرحبا', html='<p>مرحبا</p>', attach=b'%PDF-1')
        m = client.parse_message(5, raw)
        self.assertEqual((m.subject, m.sender, m.sender_address), ('عرض سعر', 'سارة', 'sara@client.com'))
        self.assertIn('مرحبا', m.text)
        self.assertIn('<p>', m.html)
        self.assertEqual([(a.filename, a.size) for a in m.attachments], [('offer.pdf', 6)])
        self.assertEqual(client.attachment_of(raw, 0)[2], b'%PDF-1')
        self.assertIsNone(client.attachment_of(raw, 3))

    def test_folder_names_decode(self):
        self.assertEqual(client.decode_name('Sent &- Co'), 'Sent & Co')
        self.assertEqual(client.decode_name('&AOk-t&AOk-'), 'été')
        self.assertEqual(client.quote('a"b'), '"a\\"b"')

    def test_header_injection_is_not_possible(self):
        class A:
            from_header, address = 'A <a@x.com>', 'a@x.com'
        msg = client.build_message(A, ['b@x.com'], [], [], 'Hi\r\nBcc: evil@x.com', 'x')
        self.assertNotIn('\n', msg['Subject'])
        self.assertIsNone(msg['Bcc'])


class MailBase(TestCase):
    def setUp(self):
        cache.clear()
        client.drop_connections()
        self.addCleanup(client.drop_connections)
        self.server = FakeServer()
        patches = [mock.patch.object(client, '_ImapSSL', lambda *a, **k: FakeImap(self.server)),
                   mock.patch.object(client, '_SmtpSSL', lambda *a, **k: FakeSmtp(self.server))]
        for p in patches:
            p.start()
            self.addCleanup(p.stop)
        self.company = make_company('Acme')
        self.users = {role: make_user(f'{role}@acme.com', self.company, role) for role in
                      (Membership.Role.OWNER, Membership.Role.ADMIN, Membership.Role.EDITOR, Membership.Role.VIEWER, Membership.Role.CLIENT)}
        self.owner = self.users[Membership.Role.OWNER]
        self.client.cookies[settings.LANGUAGE_COOKIE_NAME] = 'en'
        self.client.force_login(self.owner)

    def connect(self, password='s3cret-mail'):
        with mock.patch.object(presets, 'mx_hosts', return_value=[]):
            return self.client.post(reverse('mail:setup'), {'address': 'info@acme.com', 'display_name': 'Acme', 'password': password,
                                                           'signature': 'Acme team'})

    def events(self, action):
        return AuditEvent.all_companies.filter(company=self.company, action=action)


class MailViewsTests(MailBase):
    def test_connect_stores_the_password_sealed_and_logs_it(self):
        response = self.connect()
        self.assertRedirects(response, reverse('mail:box'), fetch_redirect_response=False)
        account = MailAccount.all_companies.get(company=self.company)
        self.assertNotIn(b's3cret-mail', bytes(account.secret))
        self.assertEqual(account.get_password(), 's3cret-mail')
        self.assertEqual((account.imap_host, account.smtp_port), ('mail.acme.com', 465))
        self.assertEqual(self.server.logins[0], ('info@acme.com', 's3cret-mail'))
        self.assertTrue(self.events(AuditEvent.MAIL_CONNECTED).exists())

    def test_the_password_is_sealed_with_this_companys_key(self):
        self.connect()
        account = MailAccount.all_companies.get()
        account.company_id = make_company('Other').pk          # read with another company's key: it does not open
        with self.assertRaises(Exception):
            account.get_password()

    def test_wrong_password_connects_nothing(self):
        self.server.fail_login = True
        response = self.connect()
        self.assertContains(response, 'refused the user name or password')
        self.assertFalse(MailAccount.all_companies.exists())

    def test_only_managers_connect_editors_use_viewers_and_clients_nothing(self):
        self.connect()
        self.client.force_login(self.users[Membership.Role.EDITOR])
        self.assertEqual(self.client.get(reverse('mail:setup')).status_code, 403)
        self.assertEqual(self.client.get(reverse('mail:box')).status_code, 200)
        self.assertEqual(self.client.post(reverse('mail:disconnect')).status_code, 403)
        for role in (Membership.Role.VIEWER, Membership.Role.CLIENT):
            self.client.force_login(self.users[role])
            for name in ('mail:box', 'mail:compose', 'mail:picker'):
                self.assertEqual(self.client.get(reverse(name)).status_code, 302, (role, name))     # sent away, nothing shown
        self.assertEqual(MailAccount.all_companies.count(), 1)

    def test_another_company_sees_nothing(self):
        self.connect()
        self.client.force_login(make_user('z@other.com', make_company('Other')))
        self.assertContains(self.client.get(reverse('mail:home')), 'not connected')
        self.assertRedirects(self.client.get(reverse('mail:box')), reverse('mail:home'), fetch_redirect_response=False)

    def test_inbox_lists_and_opens_a_message_marking_it_read_and_logging(self):
        self.connect()
        self.server.add(7, raw_message(subject='Quote please', html='<p>Hello <b>you</b></p><script>x</script>', attach=b'%PDF'))
        self.server.add(8, raw_message(subject='Second', sender='Bob <bob@x.com>'), flags='\\Seen')
        page = self.client.get(reverse('mail:box')).content.decode()
        self.assertIn('Quote please', page)
        self.assertLess(page.index('Second'), page.index('Quote please'))     # newest first
        self.assertIn('unread', page)
        opened = self.client.get(reverse('mail:box'), {'m': 7}).content.decode()
        self.assertIn('sandbox="', opened)
        self.assertNotIn('<script>x', opened)
        self.assertIn('offer.pdf', opened)
        self.assertIn('\\Seen', self.server.flags[('INBOX', 7)])
        event = self.events(AuditEvent.MAIL_OPENED).get()
        self.assertEqual(event.detail, {'sender': 'ann@client.com'})          # who and when, never the subject
        self.assertEqual(self.client.get(reverse('mail:box'))['Cache-Control'], 'private, no-store')

    def test_search_uses_a_literal_not_a_command(self):
        self.connect()
        self.server.add(1, raw_message())
        seen = []
        original = FakeImap.uid

        def spy(self_, command, *args):
            seen.append((command, args, self_.literal))
            return original(self_, command, *args)
        with mock.patch.object(FakeImap, 'uid', spy):
            self.client.get(reverse('mail:box'), {'q': 'x" ALL DELETE'})
        search = next(s for s in seen if s[0] == 'SEARCH')
        self.assertEqual(search[1][-1], 'TEXT')
        self.assertEqual(search[2], b'x" ALL DELETE')

    def test_an_unlisted_folder_falls_back_to_the_inbox(self):
        self.connect()
        self.server.add(1, raw_message(subject='In inbox'))
        self.assertContains(self.client.get(reverse('mail:box'), {'f': 'Secret"; DELETE'}), 'In inbox')

    def test_attachment_downloads_as_a_plain_file(self):
        self.connect()
        self.server.add(7, raw_message(attach=b'%PDF-data'))
        response = self.client.get(reverse('mail:attachment', args=[7, 0]))
        self.assertEqual(b''.join(response.streaming_content), b'%PDF-data')
        self.assertIn('attachment', response['Content-Disposition'])
        self.assertEqual(response['X-Content-Type-Options'], 'nosniff')
        self.assertEqual(self.client.get(reverse('mail:attachment', args=[7, 5])).status_code, 404)

    def test_actions_star_unread_delete_archive(self):
        self.connect()
        self.server.add(7, raw_message(), flags='\\Seen')
        self.client.post(reverse('mail:act'), {'op': 'star', 'uid': 7, 'f': 'INBOX'})
        self.assertIn('\\Flagged', self.server.flags[('INBOX', 7)])
        self.client.post(reverse('mail:act'), {'op': 'unread', 'uid': 7, 'f': 'INBOX'})
        self.assertNotIn('\\Seen', self.server.flags[('INBOX', 7)])
        self.client.post(reverse('mail:act'), {'op': 'archive', 'uid': 7, 'f': 'INBOX'})
        self.assertEqual((list(self.server.folders['Archive']), 7 in self.server.folders['INBOX']), ([1007], False))
        self.server.add(9, raw_message())
        self.client.post(reverse('mail:act'), {'op': 'delete', 'uid': 9, 'f': 'INBOX'})
        self.assertIn(1009, self.server.folders['Trash'])
        self.assertEqual(self.client.post(reverse('mail:act'), {'op': 'format', 'uid': 9}).status_code, 404)
        self.assertEqual(self.client.get(reverse('mail:act')).status_code, 405)

    def test_send_goes_through_smtp_keeps_a_copy_and_logs(self):
        self.connect()
        response = self.client.post(reverse('mail:compose'), {'to': 'a@client.com, B@Client.com', 'cc': 'c@client.com', 'subject': 'Offer',
                                                              'body': 'مرحبا\nSee attached'})
        self.assertRedirects(response, reverse('mail:box'), fetch_redirect_response=False)
        msg, from_addr, to_addrs = self.server.sent[0]
        self.assertEqual((from_addr, to_addrs), ('info@acme.com', ['a@client.com', 'b@client.com', 'c@client.com']))
        self.assertEqual(msg['Subject'], 'Offer')
        self.assertEqual(self.server.appended[0][0], 'Sent')
        sent = self.events(AuditEvent.MAIL_SENT).get()
        self.assertNotIn('subject', sent.detail)
        self.assertEqual(sent.detail['to'], 'a@client.com, b@client.com')

    def test_bad_recipients_and_limits(self):
        self.connect()
        for to in ('', 'not-an-address', 'a@b.com, bad'):
            self.assertContains(self.client.post(reverse('mail:compose'), {'to': to, 'body': 'x'}), 'alert-danger')
        self.assertEqual(self.server.sent, [])
        with mock.patch('apps.mail.views.SENDS_PER_HOUR', 1):
            self.client.post(reverse('mail:compose'), {'to': 'a@b.com', 'body': 'x'})
            self.client.post(reverse('mail:compose'), {'to': 'a@b.com', 'body': 'x'})
        self.assertEqual(len(self.server.sent), 1)

    def test_reply_quotes_and_addresses_the_sender(self):
        self.connect()
        self.server.add(7, raw_message(subject='Quote please', body='Line one\nLine two'))
        page = self.client.get(reverse('mail:compose'), {'reply': 7, 'f': 'INBOX'}).content.decode()
        self.assertIn('value="ann@client.com"', page)
        self.assertIn('value="Re: Quote please"', page)
        self.assertIn('<blockquote>Line one<br>Line two</blockquote>', page)
        self.assertIn('Acme team', page)
        self.assertNotIn('\\Seen', self.server.flags[('INBOX', 7)])      # replying does not mark it read by itself

    def test_the_compose_window_loads_as_a_fragment_and_answers_in_json(self):
        self.connect()
        fragment = self.client.get(reverse('mail:compose'), {'modal': 1}).content.decode()
        self.assertIn('id="compose-form"', fragment)
        self.assertNotIn('<html', fragment)
        refused = self.client.post(reverse('mail:compose'), {'modal': 1, 'to': '', 'body_html': '<p>x</p>'}).json()
        self.assertFalse(refused['ok'])
        sent = self.client.post(reverse('mail:compose'), {'modal': 1, 'to': 'a@b.com', 'subject': 'S', 'body_html': '<p>Hi <script>x</script></p>'}).json()
        self.assertTrue(sent['ok'])
        self.assertNotIn('<script', self.server.sent[0][0].as_string())

    def test_the_preview_shows_the_message_cleaned_and_loads_nothing(self):
        self.connect()
        page = self.client.post(reverse('mail:preview'), {'subject': 'S', 'body_html': '<p>Hello</p><img src="http://t/x.gif"><script>x</script>'})
        self.assertContains(page, 'Hello')
        self.assertNotContains(page, '<script')
        self.assertNotContains(page, 'http://t/x.gif')
        self.assertIn("default-src 'none'", page['Content-Security-Policy'])

    def test_disconnect_deletes_the_password(self):
        self.connect()
        self.client.post(reverse('mail:disconnect'))
        self.assertFalse(MailAccount.all_companies.exists())
        self.assertTrue(self.events(AuditEvent.MAIL_DISCONNECTED).exists())

    def test_the_connection_is_kept_between_requests(self):
        self.connect()
        self.server.add(1, raw_message())
        logins = len(self.server.logins)
        for _n in range(3):
            self.assertEqual(self.client.get(reverse('mail:box')).status_code, 200)
        self.assertEqual(len(self.server.logins), logins + 1)           # one login for the three pages
        self.client.post(reverse('mail:disconnect'))
        self.assertFalse(client._pool)

    def test_a_message_is_opened_with_one_request_and_marked_read_by_the_server(self):
        self.connect()
        self.server.add(7, raw_message())
        seen = []
        original = FakeImap.uid

        def spy(self_, command, *args):
            seen.append(command)
            return original(self_, command, *args)
        with mock.patch.object(FakeImap, 'uid', spy):
            self.client.get(reverse('mail:box'), {'m': 7})
        self.assertEqual(seen.count('STORE'), 0)
        self.assertEqual(seen.count('FETCH'), 4)                         # headers, structure and first words of the list, then the message
        self.assertIn('\\Seen', self.server.flags[('INBOX', 7)])

    def test_a_pair_of_folders_of_one_kind_shows_one(self):
        self.server.folders.update({'Sent Items': {}, 'Junk': {}, 'Spam': {}})
        self.server.add(3, raw_message(), folder='Sent Items')
        self.server.add(4, raw_message(), folder='Spam')
        self.connect()
        page = self.client.get(reverse('mail:box')).content.decode()
        menu = page[page.index('class="cat-menu"'):]
        names = re.findall(r'<span class="cat-l">([^<]+)</span>', menu)
        self.assertEqual((names.count('Sent'), names.count('Junk')), (1, 1))   # one of each pair carries our name
        self.assertTrue('?f=Sent%20Items' in page and '?f=Spam' in page)       # the fuller one of each pair
        self.assertFalse('?f=Junk"' in page or '?f=Sent"' in page)             # the empty ones are hidden

    def test_a_slow_answer_says_check_the_password_and_names_the_servers(self):
        with mock.patch.object(client, '_ImapSSL', side_effect=TimeoutError('read timed out')):
            response = self.connect()
        self.assertContains(response, 'took too long')
        self.assertContains(response, 'mail.acme.com:993')

    def test_a_dead_server_shows_a_page_not_a_crash(self):
        self.connect()
        client.drop_connections()
        with mock.patch.object(client, '_ImapSSL', side_effect=OSError('down')):
            response = self.client.get(reverse('mail:box'))
        self.assertContains(response, 'Could not reach the mail server', status_code=502)

    def test_deleting_the_company_takes_the_mailbox_with_it(self):
        self.connect()
        Company.objects.filter(pk=self.company.pk).delete()
        self.assertFalse(MailAccount.all_companies.exists())


class MailLibraryTests(MailBase):
    """Attaching issued documents and papers of the company, and keeping a received attachment in the library."""

    def paper(self, title='Trade licence', company=None):
        from django.core.files.base import ContentFile

        from apps.library.models import Record
        record = Record(company=company or self.company, title=title, category=Record.COMPANY, content_type='application/pdf', size=9)
        record.file.save('x.pdf', ContentFile(b'%PDF-1.4 x'), save=False)
        record.save()
        return record

    def document(self, **kw):
        from apps.documents.models import Document
        return Document.all_companies.create(**{**dict(company=self.company, title='Offer letter', kind='letter', language='en'), **kw})

    def test_the_picker_lists_this_company_only_and_searches(self):
        self.connect()
        self.paper('Trade licence')
        self.document(title='Offer letter')
        self.document(title='Secret of another', company=make_company('Other'))
        page = self.client.get(reverse('mail:picker')).content.decode()
        self.assertIn('Offer letter', page)
        self.assertIn('Trade licence', page)
        self.assertNotIn('Secret of another', page)
        found = self.client.get(reverse('mail:picker'), {'q': 'licence'}).content.decode()
        self.assertIn('Trade licence', found)
        self.assertNotIn('Offer letter', found)

    def test_a_paper_and_an_issued_document_travel_as_attachments(self):
        self.connect()
        record, document = self.paper(), self.document()
        with mock.patch('apps.documents.pdf.available', return_value=True), \
                mock.patch('apps.documents.views._make_pdf', return_value=b'%PDF-1.4 made') as made:
            response = self.client.post(reverse('mail:compose'), {'modal': 1, 'to': 'a@client.com', 'subject': 'Papers', 'body_html': '<p>See</p>',
                                                                  'doc': [document.pk], 'rec': [record.pk]})
        self.assertTrue(response.json()['ok'])
        made.assert_called_once()
        msg = self.server.sent[0][0]
        files = {part.get_filename(): part.get_payload(decode=True) for part in msg.iter_attachments()}
        self.assertEqual(files['offer-letter.pdf'], b'%PDF-1.4 made')
        self.assertEqual(files['trade-licence.pdf'], b'%PDF-1.4 x')

    def test_another_companys_papers_and_unapproved_or_cancelled_documents_are_refused(self):
        from django.utils import timezone
        self.connect()
        foreign = self.document(title='Foreign', company=make_company('Other'))
        foreign_paper = self.paper('Foreign paper', company=foreign.company)
        with mock.patch('apps.documents.pdf.available', return_value=True), mock.patch('apps.documents.views._make_pdf', return_value=b'%PDF-x'):
            self.client.post(reverse('mail:compose'), {'to': 'a@client.com', 'subject': 'x', 'body_html': '<p>x</p>', 'doc': [foreign.pk], 'rec': [foreign_paper.pk]})
            self.assertEqual(list(self.server.sent[0][0].iter_attachments()), [])        # nothing of the other company went out
            Company.objects.filter(pk=self.company.pk).update(documents_need_approval=True)
            draft = self.document(title='Draft', status='draft')
            response = self.client.post(reverse('mail:compose'), {'modal': 1, 'to': 'a@client.com', 'subject': 'x', 'body_html': '<p>x</p>', 'doc': [draft.pk]})
            self.assertFalse(response.json()['ok'])
            self.assertIn('not approved yet', response.json()['error'])
            cancelled = self.document(title='Cancelled', revoked_at=timezone.now())
            response = self.client.post(reverse('mail:compose'), {'modal': 1, 'to': 'a@client.com', 'subject': 'x', 'body_html': '<p>x</p>', 'doc': [cancelled.pk]})
            self.assertFalse(response.json()['ok'])
        self.assertEqual(len(self.server.sent), 1)

    def test_an_attachment_is_kept_in_the_library_and_other_types_are_refused(self):
        from apps.library.models import Record
        self.connect()
        self.server.add(7, raw_message(attach=b'%PDF-1.4 hello'))
        response = self.client.post(reverse('mail:save_attachment', args=[7, 0]), {'f': 'INBOX'})
        record = Record.all_companies.get()
        self.assertRedirects(response, reverse('library:edit', args=[record.pk]), fetch_redirect_response=False)
        self.assertEqual((record.title, record.content_type, record.category, record.uploaded_by, record.company),
                         ('offer', 'application/pdf', Record.OTHER, self.owner, self.company))
        with record.file.storage.open(record.file.name, 'rb') as f:
            self.assertEqual(f.read(), b'%PDF-1.4 hello')
        self.server.add(8, raw_message(attach=b'MZ not a pdf at all'))
        self.client.post(reverse('mail:save_attachment', args=[8, 0]), {'f': 'INBOX'})
        self.assertEqual(Record.all_companies.count(), 1)

    def test_only_keepable_attachments_offer_the_button_and_viewers_cannot_save(self):
        from apps.library.models import Record
        self.connect()
        self.server.add(7, raw_message(attach=b'%PDF-1.4 hello'))
        page = self.client.get(reverse('mail:box'), {'m': 7}).content.decode()
        self.assertIn(reverse('mail:save_attachment', args=[7, 0]), page)
        self.client.force_login(self.users[Membership.Role.VIEWER])
        self.client.post(reverse('mail:save_attachment', args=[7, 0]))
        self.assertFalse(Record.all_companies.exists())


class SnippetTests(MailBase):
    def test_each_row_shows_the_first_words_of_the_text(self):
        self.connect()
        self.server.add(1, raw_message(subject='Plain', body='Hello Sara, the offer is attached.'))
        self.server.add(2, raw_message(subject='Both', body='Plain version here', html='<html><head><style>p{color:red}</style></head><body><p>HTML <b>version</b></p></body></html>'))
        self.server.add(3, raw_message(subject='Arabic', body='مرحبا سارة، نرفق لكم العرض المطلوب'))
        page = self.client.get(reverse('mail:box')).content.decode()
        self.assertIn('Hello Sara, the offer is attached.', page)
        self.assertIn('Plain version here', page)                    # the plain part is preferred
        self.assertIn('مرحبا سارة، نرفق لكم العرض المطلوب', page)       # a base64 part is decoded

    def test_html_only_messages_show_text_without_tags_or_styles(self):
        self.assertEqual(client.snippet_of(b'<html><head><style>a{b:c}</style></head><body><p>Hi&nbsp;<b>there</b></p><script>x()</script></body>', 'html', 'utf-8', '7bit'), 'Hi there')
        self.assertEqual(client.snippet_of(b'caf=C3=A9 =\r\nau lait', 'plain', 'utf-8', 'quoted-printable'), 'café au lait')
        self.assertEqual(client.snippet_of(b'!!!not base64!!!', 'plain', 'utf-8', 'base64'), '')

    def test_the_structure_is_read_whatever_its_shape(self):
        simple = client.parse_structure(b' ("TEXT" "PLAIN" ("CHARSET" "utf-8") NIL NIL "7BIT" 10 1))')
        self.assertEqual(client.text_part(simple), ('1', 'plain', 'utf-8', '7bit'))
        nested = client.parse_structure(b' (("TEXT" "HTML" ("CHARSET" "utf-8") NIL NIL "QUOTED-PRINTABLE" 9 1)(("TEXT" "PLAIN" ("CHARSET" "iso-8859-1") NIL NIL "BASE64" 4 1)("IMAGE" "PNG" NIL NIL NIL "BASE64" 5) "ALTERNATIVE") "MIXED")')
        self.assertEqual(client.text_part(nested), ('2.1', 'plain', 'iso-8859-1', 'base64'))
        self.assertIsNone(client.text_part(client.parse_structure(b' ("IMAGE" "PNG" NIL NIL NIL "BASE64" 5))')))


TEMPLATE_HTML = ('<table role="presentation" width="640" cellpadding="0" cellspacing="0" style="width:640px;background-color:#ffffff">'
                 '<tr><td style="background-color:#7c3aed;padding:20px"><img src="{{logo}}" alt="" height="48" style="height:48px">'
                 '<span style="color:#ffffff;font-size:20px">{{company}}</span></td></tr>'
                 '<tr><td style="padding:24px;font-size:16px;line-height:1.6">{{body}}</td></tr>'
                 '<tr><td style="padding:16px;font-size:13px">{{address}} <a href="{{website}}">{{website}}</a> '
                 '<script>alert(1)</script><img src="http://track/x.gif"></td></tr></table>')


class TemplateHtmlTests(SimpleTestCase):
    def test_a_template_keeps_its_layout_and_logo_but_nothing_that_loads(self):
        html, images = htmlsafe.clean(TEMPLATE_HTML, template=True)
        self.assertIn('cellpadding="0"', html)
        self.assertIn('<img src="{{logo}}"', html)
        self.assertIn('<a href="{{website}}"', html)
        self.assertNotIn('script', html)
        self.assertNotIn('track', html)
        self.assertEqual(images, 1)                                 # only the foreign picture was left out
        plain, _n = htmlsafe.clean(TEMPLATE_HTML)                   # a message body never keeps tables' layout attributes or the logo
        self.assertNotIn('cellpadding', plain)
        self.assertNotIn('{{logo}}', plain)

    def test_fill_escapes_company_values_and_drops_an_empty_logo(self):
        from . import render
        page = render.fill(TEMPLATE_HTML.split('<script>')[0], '<p>Hi</p>', 'S', {'company': 'A <b>&</b> Co', 'address': 'Doha', 'website': ''}, '')
        self.assertIn('A &lt;b&gt;&amp;&lt;/b&gt; Co', page)
        self.assertIn('<p>Hi</p>', page)
        self.assertNotIn('<img', page)                              # no logo, no broken picture
        self.assertNotIn('{{', page)

    def test_plain_text_twin(self):
        from . import render
        self.assertEqual(render.to_text('<p>Hello</p><ul><li>One</li></ul><p>See <a href="https://a.com">here</a></p>'),
                         'Hello\n\n• One\n\nSee here (https://a.com)')


class MailTemplateViewsTests(MailBase):
    """The company's e-mail templates: paid at the price on the button, previewed, chosen and used."""

    def ai(self, html=TEMPLATE_HTML, error=None):
        from apps.ai.client import AIError, AIResult
        if error:
            return mock.patch('apps.mail.generate.ai.call_json', side_effect=AIError('Busy'))
        return mock.patch('apps.mail.generate.ai.call_json', return_value=AIResult({'html': html}, 900, 1800, 0, 'claude-opus-5-5'))

    def balance(self):
        from apps.credits.models import Wallet
        return Wallet.objects.get(company=self.company).balance

    def order(self, shown=None, **data):
        from . import generate
        data = {'style': 'modern', 'language': 'en', 'name': '', 'notes': 'green',
                'expected_points': generate.quote().total if shown is None else shown, **data}
        return self.client.post(reverse('mail:template_new'), data)

    def work(self, **ai):
        from apps.jobs.models import Job
        from apps.jobs.runner import run_job
        job = Job.objects.order_by('-pk').first()
        with self.ai(**ai):
            run_job(job)
        job.refresh_from_db()
        return job

    def make(self, **kw):
        from .models import MailTemplate
        html, _n = htmlsafe.clean(TEMPLATE_HTML, template=True)
        return MailTemplate.all_companies.create(**{**dict(company=self.company, name='Classic', html=html, language='en'), **kw})

    def test_the_price_on_the_button_is_the_price_charged(self):
        from apps.credits.models import WalletTransaction

        from . import generate
        from .models import MailTemplate
        self.owner.language = 'en'                                              # the job names the template in its maker's language
        self.owner.save(update_fields=['language'])
        quote = generate.quote()
        self.assertEqual(quote.total, 240)                                      # the owner's price: $0.24
        page = self.client.get(reverse('mail:template_new'))
        self.assertContains(page, f'name="expected_points" value="{quote.total}"')
        self.assertContains(page, f'${quote.usd}')
        before = self.balance()
        response = self.order()
        self.assertEqual(before - self.balance(), quote.total)
        self.assertEqual(WalletTransaction.objects.get(company=self.company, service_key='generate_mail_template').delta, -quote.total)
        self.assertIn(reverse('documents:working', args=[1]).rsplit('/', 2)[0], response['Location'])
        job = self.work()
        template = MailTemplate.all_companies.get()
        self.assertEqual((job.status, template.name, template.style, template.is_default, template.company), (job.Status.DONE, 'Modern', 'modern', True, self.company))
        self.assertNotIn('script', template.html)
        self.assertEqual((job.params['result_url'], job.input_tokens), (reverse('mail:templates'), 900))

    def test_a_different_price_is_refused_without_charging(self):
        from apps.jobs.models import Job
        before = self.balance()
        self.order(shown=1)
        self.assertEqual((self.balance(), Job.objects.count()), (before, 0))

    def test_a_failed_or_unusable_design_is_refunded_and_keeps_nothing(self):
        from .models import MailTemplate
        before = self.balance()
        self.order()
        self.assertEqual(self.work(error=True).status, 'failed')
        self.order()
        self.assertEqual(self.work(html='<p>no body blank here</p>').status, 'failed')
        self.assertEqual((self.balance(), MailTemplate.all_companies.count()), (before, 0))

    def test_without_balance_nothing_is_queued(self):
        from apps.credits.models import Wallet
        from apps.jobs.models import Job
        Wallet.objects.filter(company=self.company).update(balance=0)
        self.order()
        self.assertEqual(Job.objects.count(), 0)

    def test_viewers_cannot_order_a_template(self):
        from apps.jobs.models import Job
        self.client.force_login(self.users[Membership.Role.VIEWER])
        before = self.balance()
        self.order()
        self.assertEqual((Job.objects.count(), self.balance()), (0, before))

    def test_the_list_the_preview_and_who_may_delete(self):
        self.connect()
        template = self.make(is_default=True)
        self.assertContains(self.client.get(reverse('mail:templates')), 'Classic')
        page = self.client.get(reverse('mail:template_preview', args=[template.pk]))
        self.assertContains(page, 'Acme')                                    # the company name fills {{company}}
        self.assertIn("default-src 'none'", page['Content-Security-Policy'])
        self.client.force_login(self.users[Membership.Role.EDITOR])
        self.assertEqual(self.client.post(reverse('mail:template_delete', args=[template.pk])).status_code, 403)
        self.client.force_login(self.owner)
        self.client.post(reverse('mail:template_delete', args=[template.pk]))
        self.assertEqual(self.client.get(reverse('mail:template_preview', args=[template.pk])).status_code, 404)

    def test_another_company_cannot_use_my_template(self):
        self.connect()
        template = self.make()
        self.client.force_login(make_user('z@other.com', make_company('Other')))
        self.assertEqual(self.client.get(reverse('mail:template_preview', args=[template.pk])).status_code, 404)
        self.assertEqual(self.client.post(reverse('mail:template_default', args=[template.pk])).status_code, 404)

    def test_the_default_changes_and_is_chosen_in_the_composer(self):
        self.connect()
        a, b = self.make(name='A', is_default=True), self.make(name='B')
        self.client.post(reverse('mail:template_default', args=[b.pk]))
        a.refresh_from_db()
        b.refresh_from_db()
        self.assertEqual((a.is_default, b.is_default), (False, True))
        page = self.client.get(reverse('mail:compose')).content.decode()
        self.assertRegex(page, rf'name="template" value="{b.pk}" checked')

    def test_preview_shows_the_message_in_the_template(self):
        self.connect()
        template = self.make()
        page = self.client.post(reverse('mail:preview'), {'subject': 'Offer', 'body_html': '<p>Hello <b>Sara</b></p><script>x</script>',
                                                          'template': template.pk}).content.decode()
        self.assertIn('Hello <b>Sara</b>', page)
        self.assertNotIn('<script>x', page)
        self.assertIn('Acme', page)

    def test_a_message_goes_out_in_the_template_with_a_text_twin_and_the_logo_attached(self):
        from django.core.files.base import ContentFile
        self.connect()
        template = self.make()
        png = b'\x89PNG\r\n\x1a\n' + b'0' * 40
        self.company.logo.save('logo.png', ContentFile(png))
        self.client.post(reverse('mail:compose'), {'to': 'a@client.com', 'subject': 'Offer', 'template': template.pk,
                                                   'body_html': '<p>مرحبا <b>سارة</b></p><script>x</script>'})
        msg = self.server.sent[0][0]
        kinds = [part.get_content_type() for part in msg.walk()]
        self.assertIn('text/plain', kinds)
        self.assertIn('text/html', kinds)
        self.assertIn('image/png', kinds)
        html = msg.get_body(('html',)).get_content()
        self.assertIn('cid:logo', html)
        self.assertIn('<b>سارة</b>', html)
        self.assertNotIn('script', html)
        self.assertIn('مرحبا سارة', msg.get_body(('plain',)).get_content())

    def test_a_plain_message_has_no_template_and_an_empty_one_is_refused(self):
        self.connect()
        self.client.post(reverse('mail:compose'), {'to': 'a@client.com', 'subject': 'Hi', 'body_html': '<p>Hello</p>', 'template': ''})
        html = self.server.sent[0][0].get_body(('html',)).get_content()
        self.assertIn('Hello', html)
        self.assertNotIn('<table', html)
        response = self.client.post(reverse('mail:compose'), {'to': 'a@client.com', 'subject': 'Empty', 'body_html': '<p><br></p>'})
        self.assertContains(response, 'Write a message or attach a file')
        self.assertEqual(len(self.server.sent), 1)

    def test_the_waiting_page_goes_back_only_to_this_site(self):
        from apps.jobs.models import Job
        self.order()
        job = Job.objects.get()
        for back in ('javascript:alert(1)', '//evil.example/x', 'https://evil.example/'):
            page = self.client.get(reverse('documents:working', args=[job.pk]), {'back': back}).content.decode()
            self.assertNotIn(back, page)
        self.assertIn('data-back="/app/mail/templates/"', self.client.get(reverse('documents:working', args=[job.pk]), {'back': '/app/mail/templates/'}).content.decode())
