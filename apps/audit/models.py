from django.conf import settings
from django.db import models
from django.utils.translation import gettext_lazy as _

from apps.core.tenancy import CompanyScopedModel


class AuditEvent(CompanyScopedModel):
    """One thing somebody did that matters later: who, when, from where. Append-only: a row is never changed or
    removed by the application (only deleting the company takes its rows with it)."""

    DOC_REVOKED, DOC_REINSTATED = 'document.revoked', 'document.reinstated'
    DOC_QR_CHANGED, DOC_PRINTED_VERIFIABLE = 'document.qr_changed', 'document.printed_verifiable'
    DOC_OPENED, DOC_EMAILED = 'document.opened', 'document.emailed'
    COMPANY_EXPORTED = 'company.exported'
    MAIL_CONNECTED, MAIL_DISCONNECTED = 'mail.connected', 'mail.disconnected'
    MAIL_OPENED, MAIL_SENT = 'mail.opened', 'mail.sent'
    DOC_SUBMITTED, DOC_APPROVED, DOC_REJECTED = 'document.submitted', 'document.approved', 'document.rejected'
    SHARE_CREATED, SHARE_REVOKED = 'share.created', 'share.revoked'
    TEAM_INVITED, TEAM_JOINED, TEAM_REMOVED = 'team.invited', 'team.joined', 'team.removed'
    TEAM_ROLE_CHANGED, TEAM_INVITE_REVOKED = 'team.role_changed', 'team.invite_revoked'
    RECORD_UPLOADED, RECORD_CHANGED, RECORD_DELETED = 'record.uploaded', 'record.changed', 'record.deleted'
    ACTIONS = {
        DOC_QR_CHANGED: _('Added or removed the verification QR code of a document'),
        DOC_PRINTED_VERIFIABLE: _('Opened a document with a verification QR code for printing'),
        DOC_OPENED: _('Opened the text of a document'),
        DOC_EMAILED: _('Sent a document by e-mail'),
        COMPANY_EXPORTED: _('Exported all the data of the company'),
        MAIL_CONNECTED: _('Connected the company mailbox'),
        MAIL_DISCONNECTED: _('Disconnected the company mailbox'),
        MAIL_OPENED: _('Opened a message of the company mailbox'),
        MAIL_SENT: _('Sent a message from the company mailbox'),
        DOC_SUBMITTED: _('Sent a document for approval'),
        DOC_APPROVED: _('Approved a document'),
        DOC_REJECTED: _('Rejected a document'),
        DOC_REVOKED: _('Cancelled a document (its verification page now says so)'),
        DOC_REINSTATED: _('Reinstated a cancelled document'),
        SHARE_CREATED: _('Made a link to share a document'),
        SHARE_REVOKED: _('Cancelled a sharing link'),
        TEAM_INVITED: _('Invited someone to the company'),
        TEAM_JOINED: _('Joined the company'),
        TEAM_REMOVED: _('Removed a member'),
        TEAM_ROLE_CHANGED: _("Changed a member's role"),
        TEAM_INVITE_REVOKED: _('Cancelled an invitation'),
        RECORD_UPLOADED: _('Uploaded a document to the library'),
        RECORD_CHANGED: _('Changed a document of the library'),
        RECORD_DELETED: _('Deleted a document from the library'),
    }

    user = models.ForeignKey(settings.AUTH_USER_MODEL, null=True, blank=True, on_delete=models.SET_NULL, related_name='+')
    user_email = models.CharField(max_length=254, blank=True)     # kept even if the account is later deleted
    action = models.CharField(max_length=40, db_index=True)
    target = models.CharField(max_length=200, blank=True)         # what it was about: "logo", "Document 12"
    detail = models.JSONField(default=dict, blank=True)
    ip = models.GenericIPAddressField(null=True, blank=True)
    created_at = models.DateTimeField(auto_now_add=True, db_index=True)

    class Meta:
        ordering = ['-created_at', '-id']

    def __str__(self):
        return f'{self.action} {self.target}'

    @property
    def label(self):
        return self.ACTIONS.get(self.action, self.action)

    def save(self, *args, **kwargs):
        if self.pk is not None:
            raise PermissionError('An audit event is never changed.')
        super().save(*args, **kwargs)

    def delete(self, *args, **kwargs):
        raise PermissionError('An audit event is never deleted.')
