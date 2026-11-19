from datetime import datetime, time
from zoneinfo import ZoneInfo

from django import forms
from django.utils.translation import gettext_lazy as _

from .models import Note

DEFAULT_TIME = time(9, 0)           # a reminder with a date but no time is for the morning


class NoteForm(forms.ModelForm):
    # The reminder is a date and a time (two plain controls and quick choices on the page), kept in the owner's own
    # zone: the page fills `tz` from the browser, so a reminder is at their 9:00, not the server's.
    remind_date = forms.DateField(label=_('remind me at'), required=False,
                                  widget=forms.DateInput(attrs={'type': 'date', 'class': 'form-control'}, format='%Y-%m-%d'))
    remind_time = forms.TimeField(label=_('time'), required=False, input_formats=['%H:%M', '%H:%M:%S'],
                                  widget=forms.TimeInput(attrs={'type': 'time', 'class': 'form-control'}, format='%H:%M'))
    tz = forms.CharField(required=False, widget=forms.HiddenInput(attrs={'data-tz': ''}))

    class Meta:
        model = Note
        fields = ['title', 'body', 'pinned']
        widgets = {'title': forms.TextInput(attrs={'dir': 'auto', 'class': 'form-control'}),
                   'body': forms.Textarea(attrs={'rows': 5, 'dir': 'auto', 'class': 'form-control'}),
                   'pinned': forms.CheckboxInput(attrs={'class': 'form-check-input'})}

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.before = self.instance.remind_at
        if self.instance.pk:
            self.initial['tz'] = self.instance.tz
            if self.instance.remind_at:
                local = self.instance.remind_local
                self.initial['remind_date'], self.initial['remind_time'] = local.date(), local.time().replace(second=0, microsecond=0)

    def clean_tz(self):
        name = self.cleaned_data.get('tz') or 'UTC'
        try:
            ZoneInfo(name)
        except Exception:
            return 'UTC'
        return name

    def clean(self):
        cleaned = super().clean()
        day, clock = cleaned.get('remind_date'), cleaned.get('remind_time')
        self.remind_at = None
        if clock and not day:
            self.add_error('remind_date', _('Choose the date of the reminder too.'))
        elif day:
            self.remind_at = datetime.combine(day, clock or DEFAULT_TIME).replace(tzinfo=ZoneInfo(cleaned.get('tz') or 'UTC'))
        return cleaned

    def save(self, commit=True):
        note = super().save(commit=False)
        note.tz = self.cleaned_data.get('tz') or note.tz or 'UTC'
        note.remind_at = self.remind_at
        if not note.pk or note.remind_at != self.before:
            note.reminded_at, note.notified_at, note.done = None, None, False          # a new time is a new reminder
        if commit:
            note.save()
        return note
