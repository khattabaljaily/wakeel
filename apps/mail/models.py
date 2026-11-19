from django.conf import settings
from django.db import models
from django.utils.translation import gettext_lazy as _

from apps.core import filecrypto
from apps.core.tenancy import CompanyScopedModel

from .presets import SSL, STARTTLS

SECURITY = [(SSL, 'SSL/TLS'), (STARTTLS, 'STARTTLS')]


class MailAccount(CompanyScopedModel):
    """The company's one mailbox. The password is sealed with the company's key (AES-256-GCM, like the private files) and is
    never shown again after it is saved. No message is ever copied here: they stay on the company's mail server."""

    address = models.EmailField(_('e-mail address'))
    display_name = models.CharField(_('sender name'), max_length=120, blank=True)
    username = models.CharField(_('user name'), max_length=254)
    secret = models.BinaryField(editable=False, default=b'')
    imap_host = models.CharField(max_length=253)
    imap_port = models.PositiveIntegerField(default=993)
    imap_security = models.CharField(max_length=10, choices=SECURITY, default=SSL)
    smtp_host = models.CharField(max_length=253)
    smtp_port = models.PositiveIntegerField(default=465)
    smtp_security = models.CharField(max_length=10, choices=SECURITY, default=SSL)
    signature = models.TextField(_('signature'), blank=True, max_length=2000)
    last_error = models.CharField(max_length=300, blank=True, editable=False)
    connected_by = models.ForeignKey(settings.AUTH_USER_MODEL, null=True, on_delete=models.SET_NULL, related_name='+', editable=False)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        constraints = [models.UniqueConstraint(fields=['company'], name='one_mailbox_per_company')]

    def __str__(self):
        return self.address

    def set_password(self, password: str):
        self.secret = filecrypto.encrypt(settings.FILE_ENCRYPTION_KEY, self.company_id, password.encode())

    def get_password(self) -> str:
        return filecrypto.decrypt(settings.FILE_ENCRYPTION_KEY, self.company_id, bytes(self.secret)).decode()

    @property
    def from_header(self):
        from email.utils import formataddr
        return formataddr((self.display_name, self.address))


class MailTemplate(CompanyScopedModel):
    """A look for the company's e-mail (header with the logo, colours, footer with the company details) made once by the AI and
    used for any message. `html` holds the cleaned design with the blanks {{body}}, {{logo}}, {{company}}, {{address}},
    {{phone}}, {{email}}, {{website}} and {{subject}}, which are filled in when a message is shown or sent."""

    name = models.CharField(_('name'), max_length=120)
    language = models.CharField(_('language'), max_length=8, default='en')
    style = models.CharField(max_length=20, blank=True)
    html = models.TextField(editable=False)
    is_default = models.BooleanField(default=False)
    created_by = models.ForeignKey(settings.AUTH_USER_MODEL, null=True, on_delete=models.SET_NULL, related_name='+', editable=False)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ['-is_default', '-created_at']

    def __str__(self):
        return self.name
