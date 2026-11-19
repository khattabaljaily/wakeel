from django import forms
from django.conf import settings
from django.utils.translation import gettext_lazy as _

from apps.library.models import Record

from .models import Document


class DocumentForm(forms.ModelForm):
    # Which kind of document this is ("Experience certificate"): free text. The company keeps one template per type.
    doc_type = forms.CharField(label=_('Document type'), required=False, max_length=200)

    # The subject and the text are kept apart and sealed (DocumentContent), so they are form fields only.
    subject = forms.CharField(label=_('subject'), max_length=300, required=False)
    body = forms.CharField(label=_('text'), required=False, widget=forms.Textarea(attrs={'rows': 12}))

    class Meta:
        model = Document
        fields = ['category', 'doc_type', 'title', 'recipient', 'language', 'doc_date', 'include_qr']
        labels = {'title': _('Document name')}
        widgets = {'doc_date': forms.DateInput(attrs={'type': 'date'}, format='%Y-%m-%d')}

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        if self.instance.pk:
            self.initial.setdefault('subject', self.instance.subject)
            self.initial.setdefault('body', self.instance.body)
        self.fields['category'] = forms.ChoiceField(label=_('Category'), choices=Record.CATEGORIES,
                                                    initial=self.instance.category, required=False)

    def save(self, commit=True):
        self.instance.subject = self.cleaned_data.get('subject', '')
        self.instance.body = self.cleaned_data.get('body', '')
        return super().save(commit)

    def clean_category(self):
        return self.cleaned_data.get('category') or self.instance.category or Document.DEFAULT_CATEGORY[self.instance.kind]


class AIDocumentForm(forms.Form):
    """What is asked when the AI creates a document: nothing else. The name comes from the type, and the text, the
    subject and the date are shown for review after it is written."""

    doc_type = forms.CharField(
        label=_('Document type'), max_length=200, widget=forms.TextInput(attrs={'list': 'template-names', 'autocomplete': 'off'}),
        help_text=_('For example: Experience certificate. The first time, a template of it is made for your company; after that it is reused.'))
    category = forms.ChoiceField(label=_('Category'), choices=Record.CATEGORIES, required=False)
    language = forms.ChoiceField(label=_('Language'), choices=settings.LANGUAGES, required=False)
    recipient = forms.CharField(label=_('To'), max_length=200, required=False,
                                help_text=_('For example: Whom it may concern, or the name of the bank. It is printed above the text.'))
    instructions = forms.CharField(
        label=_('What should it say?'), max_length=2000, widget=forms.Textarea(attrs={'rows': 5}),
        help_text=_('Describe the purpose and the facts; the AI writes the text for you.'))
