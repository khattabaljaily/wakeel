from django import forms
from django.utils.translation import gettext_lazy as _

from apps.library.models import Record

from .models import Presentation


class PresentationForm(forms.ModelForm):
    source_record = forms.ModelChoiceField(Record.all_companies.none(), required=False, label=_('Build it from a document'),
                                           empty_label=_('No document: only what I write above'))

    class Meta:
        model = Presentation
        fields = ['title', 'brief', 'language', 'slides', 'tier', 'audience', 'tone']
        widgets = {'title': forms.TextInput(attrs={'dir': 'auto', 'class': 'form-control'}),
                   'brief': forms.Textarea(attrs={'rows': 5, 'dir': 'auto', 'class': 'form-control'}),
                   'language': forms.Select(attrs={'class': 'form-select'}),
                   'slides': forms.NumberInput(attrs={'min': Presentation.MIN_SLIDES, 'max': Presentation.MAX_SLIDES, 'class': 'form-control'}),
                   'tier': forms.RadioSelect, 'audience': forms.TextInput(attrs={'dir': 'auto', 'class': 'form-control'}),
                   'tone': forms.TextInput(attrs={'dir': 'auto', 'class': 'form-control'})}

    def __init__(self, *args, language='en', **kwargs):
        super().__init__(*args, **kwargs)
        self.fields['source_record'].queryset = Record.objects.order_by('-created_at').only('title')
        self.fields['source_record'].widget.attrs['class'] = 'form-select'
        self.fields['language'].initial = language
        self.fields['slides'].initial = 10
        self.fields['tier'].initial = Presentation.PREMIUM
        self.fields['brief'].help_text = _('The topic, the goal, the facts and figures to use. The more you write, the better it is.')
        self.fields['tier'].choices = Presentation.TIERS
        self.fields['title'].required = False                  # left empty, it is made from the topic
        self.fields['title'].help_text = _('Optional. Left empty, it is taken from what you write below.')
        self.fields['brief'].required = False                  # a document alone is enough (clean() asks for one of the two)

    def clean_slides(self):
        slides = self.cleaned_data['slides']
        if not Presentation.MIN_SLIDES <= slides <= Presentation.MAX_SLIDES:
            raise forms.ValidationError(_('Choose between %(low)d and %(high)d slides.') % {
                'low': Presentation.MIN_SLIDES, 'high': Presentation.MAX_SLIDES})
        return slides

    def clean(self):
        data = super().clean()
        if not (data.get('brief') or '').strip() and not data.get('source_record'):
            self.add_error('brief', _('Write what the presentation is about, or choose a document.'))
        return data
