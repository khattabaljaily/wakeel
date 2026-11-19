"""Server settings guessed from the address, so most people only type the address and the password."""
from dataclasses import dataclass

SSL, STARTTLS = 'ssl', 'starttls'


@dataclass
class Settings:
    imap_host: str
    imap_port: int = 993
    imap_security: str = SSL
    smtp_host: str = ''
    smtp_port: int = 465
    smtp_security: str = SSL


KNOWN = {
    'gmail.com': Settings('imap.gmail.com', smtp_host='smtp.gmail.com'),
    'googlemail.com': Settings('imap.gmail.com', smtp_host='smtp.gmail.com'),
    'outlook.com': Settings('outlook.office365.com', smtp_host='smtp.office365.com', smtp_port=587, smtp_security=STARTTLS),
    'hotmail.com': Settings('outlook.office365.com', smtp_host='smtp.office365.com', smtp_port=587, smtp_security=STARTTLS),
    'live.com': Settings('outlook.office365.com', smtp_host='smtp.office365.com', smtp_port=587, smtp_security=STARTTLS),
    'office365.com': Settings('outlook.office365.com', smtp_host='smtp.office365.com', smtp_port=587, smtp_security=STARTTLS),
    'yahoo.com': Settings('imap.mail.yahoo.com', smtp_host='smtp.mail.yahoo.com'),
    'icloud.com': Settings('imap.mail.me.com', smtp_host='smtp.mail.me.com', smtp_port=587, smtp_security=STARTTLS),
    'me.com': Settings('imap.mail.me.com', smtp_host='smtp.mail.me.com', smtp_port=587, smtp_security=STARTTLS),
    'zoho.com': Settings('imap.zoho.com', smtp_host='smtp.zoho.com'),
    'zohomail.com': Settings('imap.zoho.com', smtp_host='smtp.zoho.com'),
    'fastmail.com': Settings('imap.fastmail.com', smtp_host='smtp.fastmail.com'),
    'gmx.com': Settings('imap.gmx.com', smtp_host='mail.gmx.com'),
    'aol.com': Settings('imap.aol.com', smtp_host='smtp.aol.com'),
}


# Who runs a company's mail is read from its MX records: a company's own domain usually points at a provider.
BY_MX = {
    'privateemail.com': Settings('mail.privateemail.com', smtp_host='mail.privateemail.com'),
    'google.com': KNOWN['gmail.com'], 'googlemail.com': KNOWN['gmail.com'],
    'outlook.com': KNOWN['outlook.com'], 'protection.outlook.com': KNOWN['outlook.com'],
    'zoho.com': KNOWN['zoho.com'], 'zoho.eu': Settings('imap.zoho.eu', smtp_host='smtp.zoho.eu'),
    'secureserver.net': Settings('imap.secureserver.net', smtp_host='smtpout.secureserver.net'),
    'hostinger.com': Settings('imap.hostinger.com', smtp_host='smtp.hostinger.com'),
    'mail.hostinger.com': Settings('imap.hostinger.com', smtp_host='smtp.hostinger.com'),
    'fastmail.com': KNOWN['fastmail.com'], 'messagingengine.com': KNOWN['fastmail.com'],
    'yandex.net': Settings('imap.yandex.com', smtp_host='smtp.yandex.com'),
    'mail.ru': Settings('imap.mail.ru', smtp_host='smtp.mail.ru'),
    'icloud.com': KNOWN['icloud.com'],
}


def mx_hosts(domain: str) -> list:
    try:
        import dns.exception
        import dns.resolver
        answers = dns.resolver.resolve(domain, 'MX', lifetime=4)
        return [str(r.exchange).rstrip('.').lower() for r in sorted(answers, key=lambda r: r.preference)]
    except Exception:       # no records, no network, no library: fall back to the usual guess
        return []


def guess(address: str) -> Settings:
    """Known providers by the domain; else by the provider named in the MX records; else the usual `mail.<domain>`."""
    domain = address.rsplit('@', 1)[-1].strip().lower()
    if domain in KNOWN:
        return Settings(**KNOWN[domain].__dict__)
    for host in mx_hosts(domain):
        for suffix, found in BY_MX.items():
            if host == suffix or host.endswith('.' + suffix):
                return Settings(**found.__dict__)
    return Settings(f'mail.{domain}', smtp_host=f'mail.{domain}')
