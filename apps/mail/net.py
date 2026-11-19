"""Network safety for connecting to a mail server whose name a user typed.

Without this, "mail server: 127.0.0.1, port 5432" would make our server probe its own network for the user. Only the
ports mail servers use are allowed, the name is resolved ONCE, every address must be a public one, and the connection
goes to that address (so a name that changes its answer between the check and the connection gains nothing)."""
import ipaddress
import socket

from django.conf import settings

IMAP_PORTS = (143, 993)
SMTP_PORTS = (25, 465, 587, 2525)
TIMEOUT = 20


class UnsafeHost(OSError):
    """The server name or port is not allowed."""


def public_address(host: str, port: int) -> str:
    host = (host or '').strip().rstrip('.')
    if not host or len(host) > 253 or any(c.isspace() or c in '/\\@' for c in host):
        raise UnsafeHost('invalid host')
    try:
        found = socket.getaddrinfo(host, port, type=socket.SOCK_STREAM)
    except socket.gaierror as exc:
        raise UnsafeHost('unknown host') from exc
    allow_private = getattr(settings, 'MAIL_ALLOW_PRIVATE_HOSTS', False)
    chosen = None
    for family, _t, _p, _c, sockaddr in found:
        ip = ipaddress.ip_address(sockaddr[0].split('%')[0])
        if not allow_private and not ip.is_global:
            raise UnsafeHost('private address')
        chosen = chosen or sockaddr[0]
    if chosen is None:
        raise UnsafeHost('unknown host')
    return chosen


def open_socket(host: str, port: int, timeout: int = TIMEOUT):
    return socket.create_connection((public_address(host, port), port), timeout)


def check_imap_port(port: int):
    if port not in IMAP_PORTS:
        raise UnsafeHost('port')


def check_smtp_port(port: int):
    if port not in SMTP_PORTS:
        raise UnsafeHost('port')
