import re

from django import forms
from django.conf import settings
from django.core.validators import validate_email
from django.utils.translation import gettext_lazy as _

from . import net, presets
from .models import SECURITY

HOST = re.compile(r'^[A-Za-z0-9]([A-Za-z0-9.-]{0,251}[A-Za-z0-9])?$')


class SetupForm(forms.Form):
    """Address and password are enough for most mailboxes; the server details are guessed from the address and can be corrected."""

    address = forms.EmailField(label=_('Company e-mail address'), widget=forms.EmailInput(attrs={'dir': 'ltr', 'autocomplete': 'off'}))
    display_name = forms.CharField(label=_('Sender name'), max_length=120, required=False,
                                   help_text=_('Shown to the people you write to. Usually the company name.'))
    password = forms.CharField(label=_('Mailbox password'), required=False, strip=False,
                               widget=forms.PasswordInput(attrs={'autocomplete': 'new-password', 'dir': 'ltr'}),
                               help_text=_('Kept sealed and never shown again. Gmail, Outlook and Yahoo need an app password, not the normal one.'))
    username = forms.CharField(label=_('User name'), max_length=254, required=False, widget=forms.TextInput(attrs={'dir': 'ltr'}),
                               help_text=_('Leave empty to use the e-mail address.'))
    imap_host = forms.CharField(label=_('Incoming server (IMAP)'), max_length=253, required=False, widget=forms.TextInput(attrs={'dir': 'ltr'}))
    imap_port = forms.TypedChoiceField(label=_('Port'), coerce=int, choices=[(993, '993'), (143, '143')], required=False)
    imap_security = forms.ChoiceField(label=_('Security'), choices=SECURITY, required=False)
    smtp_host = forms.CharField(label=_('Outgoing server (SMTP)'), max_length=253, required=False, widget=forms.TextInput(attrs={'dir': 'ltr'}))
    smtp_port = forms.TypedChoiceField(label=_('Port'), coerce=int, choices=[(465, '465'), (587, '587'), (25, '25'), (2525, '2525')], required=False)
    smtp_security = forms.ChoiceField(label=_('Security'), choices=SECURITY, required=False)
    signature = forms.CharField(label=_('Signature'), max_length=2000, required=False, widget=forms.Textarea(attrs={'rows': 3}),
                                help_text=_('Added at the end of every new message.'))

    def __init__(self, *args, existing=None, **kwargs):
        super().__init__(*args, **kwargs)
        self.existing = existing
        for name, field in self.fields.items():
            field.widget.attrs['class'] = 'form-select' if isinstance(field.widget, forms.Select) else 'form-control'

    def clean_address(self):
        return self.cleaned_data['address'].strip().lower()

    def clean(self):
        data = super().clean()
        address = data.get('address')
        if not address:
            return data
        if not data.get('password') and not self.existing:
            self.add_error('password', _('Enter the mailbox password.'))
        guess = presets.guess(address)
        for key in ('imap_host', 'imap_port', 'imap_security', 'smtp_host', 'smtp_port', 'smtp_security'):
            if not data.get(key):
                data[key] = getattr(guess, key)
        data['imap_port'], data['smtp_port'] = int(data['imap_port']), int(data['smtp_port'])
        data['username'] = (data.get('username') or address).strip()
        for key in ('imap_host', 'smtp_host'):
            data[key] = data[key].strip().lower()
            if not HOST.match(data[key]):
                self.add_error(key, _('Enter the server name only, such as mail.example.com.'))
        try:
            net.check_imap_port(data['imap_port'])
            net.check_smtp_port(data['smtp_port'])
        except net.UnsafeHost:
            self.add_error(None, _('Use the usual mail ports (993 or 143 to read, 465, 587, 25 or 2525 to send).'))
        return data


def split_recipients(text):
    """Addresses typed with commas, semicolons or line breaks -> (valid list, first invalid text or '')."""
    found = []
    for part in re.split(r'[,;\n]+', text or ''):
        part = part.strip()
        if not part:
            continue
        match = re.search(r'<([^<>]+)>\s*$', part)
        address = (match.group(1) if match else part).strip()
        try:
            validate_email(address)
        except forms.ValidationError:
            return found, part
        found.append(address.lower())
    return list(dict.fromkeys(found)), ''


class TemplateForm(forms.Form):
    name = forms.CharField(label=_('Template name'), max_length=120, required=False,
                           help_text=_('Optional. Leave it empty to use the name of the style.'),
                           widget=forms.TextInput(attrs={'class': 'form-control', 'dir': 'auto'}))
    style = forms.ChoiceField(label=_('Style'), widget=forms.RadioSelect)
    language = forms.ChoiceField(label=_('Language of the template'), choices=settings.LANGUAGES, widget=forms.Select(attrs={'class': 'form-select'}))
    notes = forms.CharField(label=_('Anything you want in it'), required=False, max_length=1000,
                            widget=forms.Textarea(attrs={'rows': 3, 'class': 'form-control', 'dir': 'auto'}),
                            help_text=_('For example: a green header, a short line about our opening hours in the footer.'))

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        from .generate import STYLES
        self.fields['style'].choices = [(key, label) for key, (label, _d) in STYLES.items()]
