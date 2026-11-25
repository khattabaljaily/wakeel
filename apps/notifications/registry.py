"""What can be notified by kind, and how it reads. A notification of a kind stores the kind and the values that go into
the sentence (never the finished text), so each person reads it in their own language, whoever caused it. (The older
notifications of the marketing section store their finished sentence in `message`.)

To add a kind: put it in KINDS with an icon (a Bootstrap icon class) and a sentence (translated like any string), then
call `services.notify_event()`. An app that has things to say on its own clock (a reminder whose time has come) adds a
collector: a function `(user, company)` that calls `notify_event()`; the bell runs the collectors when a page is drawn."""
from django.utils.translation import gettext_lazy as _

KINDS = {
    'reminder': ('bi-clock', _('Reminder: %(title)s')),
    'task_assigned': ('bi-check2-square', _('%(who)s gave you a task: %(title)s')),
    'task_comment': ('bi-check2-square', _('%(who)s wrote on the task: %(title)s')),
    'document_pending': ('bi-file-earmark-text', _('%(who)s sent a document for approval: %(title)s')),
    'document_approved': ('bi-check-circle', _('Your document was approved: %(title)s')),
    'document_rejected': ('bi-x-circle', _('Your document was rejected: %(title)s')),
    'expiring': ('bi-folder', _('%(title)s expires on %(date)s')),
    'expired': ('bi-folder', _('%(title)s expired on %(date)s')),
    'announcement': ('bi-megaphone', _('New announcement: %(title)s')),
    'announcement_ack': ('bi-megaphone', _('Please confirm you read: %(title)s')),
    'wallet_low': ('bi-wallet2', _('The balance is low: %(balance)s left. Top up to keep using the services')),
    'wallet_empty': ('bi-wallet2', _('The balance is finished. Top up to keep using the services')),
    'form_answer': ('bi-ui-checks', _('New answer on the form: %(title)s')),
    'autopilot_paused': ('bi-pause-circle', _('The autopilot is waiting for a top-up: it needs %(needed)s and the balance is %(balance)s')),
    'report_skipped': ('bi-graph-up', _('The monthly report was not made: the balance is %(balance)s and it needs %(needed)s')),
    'operator_changed': ('bi-building', _('Your company is now served and billed by %(operator)s')),
    'member_joined': ('bi-person-plus', _('%(who)s joined the company')),
}

COLLECTORS = []


def collector(fn):
    COLLECTORS.append(fn)
    return fn
