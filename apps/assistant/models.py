from datetime import timedelta

from django.conf import settings
from django.db import models
from django.utils import timezone
from django.utils.translation import gettext_lazy as _

from apps.core.tenancy import CompanyScopedModel

PROPOSAL_LIFETIME = timedelta(hours=24)       # a price shown a day ago is not a price to charge today


class Message(CompanyScopedModel):
    """One line of a person's conversation with Marid (private to that person)."""

    USER, ASSISTANT = 'user', 'assistant'
    user = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.CASCADE, related_name='+')
    role = models.CharField(max_length=10, choices=[(USER, 'user'), (ASSISTANT, 'assistant')])
    text = models.TextField()
    created_at = models.DateTimeField(auto_now_add=True, db_index=True)

    class Meta:
        ordering = ['created_at', 'id']
        indexes = [models.Index(fields=['company', 'user'])]


class Proposal(CompanyScopedModel):
    """What Marid suggests doing. Nothing runs until the person approves it; the price and the permission are checked again
    at that moment, from the saved parameters, never from what the model said."""

    PROPOSED, RUNNING, DONE, FAILED, DISMISSED = 'proposed', 'running', 'done', 'failed', 'dismissed'
    STATUSES = [(PROPOSED, _('Waiting for you')), (RUNNING, _('Running')), (DONE, _('Done')), (FAILED, _('Failed')),
                (DISMISSED, _('Dismissed'))]
    user = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.CASCADE, related_name='+')
    message = models.ForeignKey(Message, on_delete=models.CASCADE, related_name='proposals')
    action = models.CharField(max_length=40)
    params = models.JSONField(default=dict)
    status = models.CharField(max_length=10, choices=STATUSES, default=PROPOSED, db_index=True)
    outcome = models.CharField(max_length=300, blank=True)          # what happened, safe to show
    url = models.CharField(max_length=200, blank=True)              # where to see the result
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ['id']

    @property
    def expired(self):
        return self.status == self.PROPOSED and timezone.now() - self.created_at > PROPOSAL_LIFETIME

    @property
    def can_approve(self):
        return self.status == self.PROPOSED and not self.expired
