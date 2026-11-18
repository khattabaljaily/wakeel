from django import forms
from django.conf import settings
from django.utils.translation import gettext_lazy as _

from .pdfimage import PdfNotUsable, first_page_png, is_pdf

# A letterhead is a whole page (often a PDF), so it may be bigger than a logo.
MAX_LETTERHEAD_BYTES = 5 * 1024 * 1024
LETTERHEAD_WIDGET = forms.FileInput(attrs={'accept': 'application/pdf,image/png,image/jpeg,image/webp'})


class LetterheadField(forms.ImageField):
    """An image, or a PDF whose first page becomes the image."""

    def to_python(self, data):
        if data is not None and hasattr(data, 'read') and is_pdf(data):
            if data.size > MAX_LETTERHEAD_BYTES:
                raise forms.ValidationError(_('The file must be smaller than 5 MB.'))
            try:
                data = first_page_png(data)
            except PdfNotUsable:
                raise forms.ValidationError(_('This PDF could not be read. Save it again without a password, or upload an image.'))
        return super().to_python(data)


class LetterheadUploadForm(forms.Form):
    """Add or replace the letterhead of one language: an image, or a PDF whose first page becomes the image."""

    language = forms.ChoiceField(label=_('Language'), choices=settings.LANGUAGES)
    file = LetterheadField(label=_('Letterhead'), widget=LETTERHEAD_WIDGET)

    def clean_file(self):
        upload = self.cleaned_data['file']
        if getattr(upload, 'size', 0) > MAX_LETTERHEAD_BYTES:
            raise forms.ValidationError(_('The image must be smaller than %(mb)d MB.') % {'mb': MAX_LETTERHEAD_BYTES // (1024 * 1024)})
        return upload


class OtherNamesMixin:
    """The name and address in languages other than the main one, posted as parallel lists (other_lang, other_name,
    other_address) and kept in `other_names`. Empty rows are dropped."""

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        if self.is_bound:
            d = self.data
            rows = zip(d.getlist('other_lang'), d.getlist('other_name'), d.getlist('other_address'))
            self.other_rows = [{'lang': lang, 'name': name.strip(), 'address': address.strip()} for lang, name, address in rows]
        else:
            self.other_rows = [{'lang': lang, **values} for lang, values in (self.instance.other_names or {}).items()]

    def clean(self):
        cleaned = super().clean()
        known = dict(settings.LANGUAGES)
        main = cleaned.get('main_language')
        names = {}
        for row in self.other_rows:
            if not (row['name'] or row['address']):
                continue
            if row['lang'] not in known or row['lang'] == main or row['lang'] in names:
                raise forms.ValidationError(_('Choose a different language for each extra name.'))
            names[row['lang']] = {k: row[k][:400] for k in ('name', 'address') if row[k]}
        self.instance.other_names = names
        return cleaned
