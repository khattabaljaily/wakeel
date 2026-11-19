"""A note's reminder goes through the notification centre: when its time comes it becomes a notification (the bell and the
Notifications page; made when the member's page is drawn, or by the scheduled job, whichever is first), and the job also
e-mails it once, in the member's language, unless they turned the e-mails off in their account. A new reminder time starts it
again. Run the job every few minutes (`manage.py send_note_reminders`, from cron): the e-mail is for when the member is not
in the app."""
import logging

from django.conf import settings
from django.core.mail import send_mail
from django.db.models import Q
from django.template.loader import render_to_string
from django.urls import reverse
from django.utils import timezone, translation

from apps.notifications.services import notify_event

from .models import Note

logger = logging.getLogger(__name__)


def _url():
    return reverse('notes:list') + '?show=reminders'


def notify_due(note, now=None):
    """Put one due reminder in the centre (once: a second call does nothing)."""
    now = now or timezone.now()
    notify_event(note.owner, 'reminder', company=note.company, url=_url(), title=note.title,
                 dedupe_key=f'note:{note.pk}:{int(note.remind_at.timestamp())}')
    Note.all_companies.filter(pk=note.pk).update(notified_at=now)


def collect(user, company):
    """The centre's collector, run when a member's page is drawn: their due reminders in this company become notifications."""
    now = timezone.now()
    for note in Note.all_companies.filter(company=company, owner=user, done=False, notified_at__isnull=True,
                                          remind_at__lte=now).select_related('company', 'owner'):
        notify_due(note, now)


def _email(note):
    """The reminder by e-mail, with the note itself. True when the mail server took it."""
    user = note.owner
    with translation.override(user.language or settings.LANGUAGE_CODE):
        # The time is isolated left-to-right (U+2066…U+2069) so it is not reversed inside an Arabic sentence.
        context = {'note': note, 'when': f'⁦{note.remind_display}⁩', 'company': note.company.name,
                   'url': settings.SITE_URL.rstrip('/') + _url(), 'user': user}
        subject = render_to_string('notes/emails/reminder_subject.txt', context).strip()
        body = render_to_string('notes/emails/reminder.txt', context)
    try:
        send_mail(subject, body, None, [user.email])
    except Exception:              # an e-mail outage must not stop the other reminders; this one is tried again next run
        logger.exception('Could not e-mail the reminder of note %s', note.pk)
        return False
    return True


def send_due(now=None):
    """The scheduled job. Returns the number of e-mails sent; a reminder counts as e-mailed only when the mail server took it
    (a member who turned the e-mails off gets the notification only)."""
    now = now or timezone.now()
    sent = 0
    due = Note.all_companies.filter(done=False, remind_at__lte=now, owner__is_active=True).filter(
        Q(reminded_at__isnull=True) | Q(notified_at__isnull=True))
    for note in due.select_related('owner', 'company'):
        if note.notified_at is None:
            notify_due(note, now)
        if note.reminded_at is not None:
            continue
        if not (note.owner.email and note.owner.email_notifications):
            Note.all_companies.filter(pk=note.pk).update(reminded_at=now)
            continue
        if _email(note):
            Note.all_companies.filter(pk=note.pk).update(reminded_at=now)
            sent += 1
    return sent
