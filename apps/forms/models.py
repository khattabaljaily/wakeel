import secrets

from django.conf import settings
from django.db import models
from django.utils import timezone
from django.utils.translation import gettext_lazy as _

from apps.core.tenancy import CompanyScopedModel


def new_code():
    return secrets.token_urlsafe(9)         # 12 characters, random: the link is the key, so it cannot be guessed


class Form(CompanyScopedModel):
    """A form or survey the company shares by a link or a QR code, and the answers it collects."""

    PUBLIC, TEAM = 'public', 'team'
    AUDIENCES = [(PUBLIC, _('Anyone with the link (no name asked)')),
                 (TEAM, _('Only the people of this company, one answer each'))]

    title = models.CharField(_('title'), max_length=200)
    description = models.TextField(_('description'), blank=True, help_text=_('Shown above the questions.'))
    audience = models.CharField(_('who can answer'), max_length=8, choices=AUDIENCES, default=PUBLIC)
    is_open = models.BooleanField(_('accepting answers'), default=True)
    closes_on = models.DateField(_('closes on'), null=True, blank=True, help_text=_('Optional: it stops accepting answers after this day.'))
    thanks = models.CharField(_('message after sending'), max_length=300, blank=True, help_text=_('Optional. Shown after someone sends their answers.'))
    code = models.CharField(max_length=24, unique=True, default=new_code, editable=False)
    author = models.ForeignKey(settings.AUTH_USER_MODEL, null=True, blank=True, on_delete=models.SET_NULL,
                               related_name='+', editable=False)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ['-created_at', '-id']

    def __str__(self):
        return self.title

    @property
    def accepting(self):
        """It takes answers right now: switched on, and its last day (if any) has not passed."""
        return self.is_open and (self.closes_on is None or self.closes_on >= timezone.localdate())


class Question(CompanyScopedModel):
    SHORT, LONG, CHOICE, MULTI, RATING, DATE = 'short', 'long', 'choice', 'multi', 'rating', 'date'
    KINDS = [(SHORT, _('Short text')), (LONG, _('Long text')), (CHOICE, _('Choose one')),
             (MULTI, _('Choose several')), (RATING, _('Rating from 1 to 5')), (DATE, _('Date'))]
    WITH_OPTIONS = (CHOICE, MULTI)

    form = models.ForeignKey(Form, on_delete=models.CASCADE, related_name='questions')
    position = models.PositiveIntegerField(default=0)
    kind = models.CharField(_('type'), max_length=8, choices=KINDS, default=SHORT)
    text = models.CharField(_('question'), max_length=300)
    options = models.TextField(_('choices'), blank=True, help_text=_('One choice per line.'))
    required = models.BooleanField(_('required'), default=False)

    class Meta:
        ordering = ['position', 'id']

    def __str__(self):
        return self.text

    @property
    def choices(self):
        return [line.strip() for line in self.options.splitlines() if line.strip()]


class Response(CompanyScopedModel):
    """One person's answers. `user` is set only for a team form (one answer each); a public form keeps no name."""

    form = models.ForeignKey(Form, on_delete=models.CASCADE, related_name='responses')
    user = models.ForeignKey(settings.AUTH_USER_MODEL, null=True, blank=True, on_delete=models.SET_NULL, related_name='+')
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ['-created_at', '-id']


class Answer(CompanyScopedModel):
    """The answer to one question. A text, a date (as ISO text) or a rating is in `value`; several choices are in `values`."""

    response = models.ForeignKey(Response, on_delete=models.CASCADE, related_name='answers')
    question = models.ForeignKey(Question, on_delete=models.CASCADE, related_name='answers')
    value = models.TextField(blank=True)
    values = models.JSONField(default=list, blank=True)

    @property
    def shown(self):
        return ', '.join(self.values) if self.question.kind == Question.MULTI else self.value
