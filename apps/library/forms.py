from django import forms
from django.utils.translation import gettext_lazy as _

from .models import Record

MAX_BYTES = 10 * 1024 * 1024


def sniff(upload):
    """The real type of an uploaded file from its first bytes; None when it is not a PDF or a supported image."""
    head = upload.read(16)
    upload.seek(0)
    if head.startswith(b'%PDF-'):
        return 'application/pdf'
    if head.startswith(b'\x89PNG\r\n\x1a\n'):
        return 'image/png'
    if head.startswith(b'\xff\xd8\xff'):
        return 'image/jpeg'
    if head[:4] == b'RIFF' and head[8:12] == b'WEBP':
        return 'image/webp'
    return None


class RecordForm(forms.ModelForm):
    # On a new upload the details are read automatically unless the member turns it off (the price is shown on the box).
    read = forms.BooleanField(label=_('Read the details automatically'), required=False, initial=True)
    expected_points = forms.IntegerField(required=False, widget=forms.HiddenInput)

    class Meta:
        model = Record
        fields = ['title', 'category', 'file', 'doc_type', 'issuer', 'reference', 'issue_date', 'expiry_date', 'notes']
        widgets = {
            'file': forms.FileInput(attrs={'accept': 'application/pdf,image/png,image/jpeg,image/webp'}),
            'issue_date': forms.DateInput(attrs={'type': 'date'}, format='%Y-%m-%d'),
            'expiry_date': forms.DateInput(attrs={'type': 'date'}, format='%Y-%m-%d'),
            'notes': forms.Textarea(attrs={'rows': 3}),
        }

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        # A new record needs its file; an existing one keeps its file unless a new one is chosen.
        self.fields['file'].required = not self.instance.pk
        if self.instance.pk:
            del self.fields['read']                  # an existing record is read again from its own button
        # A bound form decides from what was sent; a first display offers the reading, ticked.
        self.reading = not self.instance.pk and (not self.is_bound or self.data.get('read') == 'on')
        if self.reading:
            self.fields['title'].required = False    # the document's own title is used when the name is left empty
        for name in ('title', 'doc_type', 'issuer', 'reference', 'notes'):
            self.fields[name].widget.attrs['dir'] = 'auto'
        self.fields['doc_type'].widget.attrs['list'] = 'known-types'   # the company's own types, as suggestions

    def clean_file(self):
        upload = self.cleaned_data.get('file')
        if not upload or upload == self.instance.file:
            return upload
        if upload.size > MAX_BYTES:
            raise forms.ValidationError(_('The file must be smaller than 10 MB.'))
        kind = sniff(upload)
        if kind is None:
            raise forms.ValidationError(_('The file must be a PDF, PNG, JPG or WebP.'))
        self.instance.content_type = kind
        self.instance.size = upload.size
        return upload

    def clean(self):
        cleaned = super().clean()
        if not self.instance.pk:
            self.reading = bool(cleaned.get('read'))
            if not self.reading and not cleaned.get('title'):
                self.add_error('title', _('Write a name for the document, or let it be read automatically.'))
        issued, expires = cleaned.get('issue_date'), cleaned.get('expiry_date')
        if issued and expires and expires < issued:
            self.add_error('expiry_date', _('The expiry date cannot be before the issue date.'))
        return cleaned
